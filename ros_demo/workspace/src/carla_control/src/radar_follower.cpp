// Written by GPT 6
// TODO: REPLACE WITH A GOOD SIMPLE EXAMPLE

#include <rclcpp/rclcpp.hpp>
#include <rclcpp/create_timer.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <carla_msgs/msg/carla_ego_vehicle_control.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std::chrono_literals;

class RadarFollower : public rclcpp::Node {
  using WallClock = std::chrono::steady_clock;

  struct Hit {
    double range;
    double velocity;
  };

  // Enable /clock by default. No extra message dependency is needed:
  // rclcpp's TimeSource subscribes to /clock when use_sim_time is true.
  static rclcpp::NodeOptions simOptions() {
    rclcpp::NodeOptions options;
    options.parameter_overrides({rclcpp::Parameter("use_sim_time", true)});
    return options;
  }

public:
  RadarFollower() : Node("lidar_follower", simOptions()) {
    gap_ = std::max(1.0, declare_parameter<double>("target_gap", 5.0));
    half_width_ = std::max(0.5, declare_parameter<double>("half_width", 1.4));
    cruise_throttle_ = std::clamp(
        declare_parameter<double>("cruise_throttle", 0.45), 0.0, 1.0);
    startup_throttle_ = std::clamp(
        declare_parameter<double>("startup_throttle", 0.35), 0.0, 1.0);
    max_throttle_ = std::clamp(
        declare_parameter<double>("max_throttle", 0.65), 0.0, 1.0);
    min_points_ = static_cast<int>(std::max<int64_t>(
        1, declare_parameter<int64_t>("min_points", 2)));

    const auto radar_topic = declare_parameter<std::string>(
        "radar_topic", "/carla/hero/front_radar/point_cloud");
    const auto control_topic = declare_parameter<std::string>(
        "control_topic", "/carla/hero/vehicle_control_cmd");

    radar_sub_ = create_subscription<sensor_msgs::msg::PointCloud2>(
        radar_topic, rclcpp::SensorDataQoS(),
        std::bind(&RadarFollower::onRadar, this, std::placeholders::_1));

    control_pub_ = create_publisher<carla_msgs::msg::CarlaEgoVehicleControl>(
        control_topic, rclcpp::QoS(10).reliable());

    // 20 ms of SIMULATION time, not wall time. At 3x real-time the
    // control loop is consequently called about 150 times per wall second.
    sim_timer_ = rclcpp::create_timer(
        get_node_base_interface(), get_node_timers_interface(), get_clock(),
        rclcpp::Duration::from_seconds(0.020),
        [this]() { publishControl(); });

    // Keep publishing startup/control commands when /clock is paused,
    // before the first scene, or during DDS reconnection. This does NOT
    // advance the controller's simulated-time integrator.
    wall_timer_ = create_wall_timer(
        50ms, [this]() { publishControl(); });

    RCLCPP_INFO(get_logger(),
                "Radar follower: sim clock enabled, 20 ms SIM timer, "
                "50 ms wall fallback, %.1f m desired gap", gap_);
    RCLCPP_INFO(get_logger(), "Radar: %s | Control: %s",
                radar_topic.c_str(), control_topic.c_str());
  }

private:
  double simNow() const {
    // The ROS clock follows CARLA's /clock because use_sim_time=true.
    // Until the first /clock message it is zero; in that case a radar
    // header timestamp, if available, is better than zero.
    const double ros_time = get_clock()->now().seconds();
    // A sensor sample can arrive one /clock callback ahead of the
    // TimeSource subscription; do not temporarily treat it as "future".
    return std::max(ros_time, last_radar_stamp_);
  }

  void clearTarget() {
    have_target_ = false;
    target_range_ = 0.0;
    target_velocity_ = 0.0;
    last_target_sim_ = -1.0;
    nearest_ = std::numeric_limits<double>::infinity();
  }

  void resetEpisode(const char *why) {
    clearTarget();
    have_radar_ = false;
    last_radar_stamp_ = 0.0;
    last_radar_wall_ = WallClock::time_point{};
    last_control_sim_ = -1.0;
    last_raw_clock_ = 0.0;
    throttle_ = 0.0;
    brake_ = 0.0;
    RCLCPP_INFO(get_logger(), "Scenic scene/reset: %s", why);
  }

  void onRadar(const sensor_msgs::msg::PointCloud2::SharedPtr msg) {
    const double stamp = static_cast<double>(msg->header.stamp.sec) +
                         1e-9 * static_cast<double>(msg->header.stamp.nanosec);

    if (stamp > 0.0 && last_radar_stamp_ > 0.0 &&
        stamp < last_radar_stamp_ - 0.05) {
      resetEpisode("radar timestamp went backwards");
    }

    // Headers and /clock refer to the same CARLA simulation clock.
    if (stamp > 0.0) last_radar_stamp_ = stamp;
    last_radar_wall_ = WallClock::now();

    if (!have_radar_) {
      RCLCPP_INFO(get_logger(), "Radar stream connected");
    }
    have_radar_ = true;
    nearest_ = std::numeric_limits<double>::infinity();

    std::vector<Hit> hits;
    hits.reserve(static_cast<size_t>(msg->width) * msg->height);

    try {
      sensor_msgs::PointCloud2ConstIterator<float> x(*msg, "x");
      sensor_msgs::PointCloud2ConstIterator<float> y(*msg, "y");
      sensor_msgs::PointCloud2ConstIterator<float> z(*msg, "z");
      sensor_msgs::PointCloud2ConstIterator<float> depth(*msg, "depth");
      sensor_msgs::PointCloud2ConstIterator<float> velocity(*msg, "velocity");

      for (; x != x.end(); ++x, ++y, ++z, ++depth, ++velocity) {
        if (!std::isfinite(*x) || !std::isfinite(*y) ||
            !std::isfinite(*z) || !std::isfinite(*depth) ||
            !std::isfinite(*velocity)) {
          continue;
        }

        // Keep returns in a narrow corridor in front of the ego car.
        if (*x <= 0.5f || std::abs(*y) > half_width_ ||
            *z < -1.15f || *z > 1.0f ||
            *depth < 0.8f || *depth > 60.0f) {
          continue;
        }

        hits.push_back({*depth, *velocity});
        nearest_ = std::min(nearest_, static_cast<double>(*depth));
      }
    } catch (const std::runtime_error &e) {
      RCLCPP_ERROR(get_logger(), "Radar point fields: %s", e.what());
      return;
    }

    std::sort(hits.begin(), hits.end(), [](const Hit &a, const Hit &b) {
      return a.range < b.range;
    });

    // Nearest group with at least min_points returns within 1.5 m depth.
    bool found = false;
    double range = 0.0;
    double raw_velocity = 0.0;
    for (size_t i = 0; i < hits.size(); ++i) {
      size_t j = i;
      while (j < hits.size() && hits[j].range - hits[i].range <= 1.5) {
        ++j;
      }
      if (static_cast<int>(j - i) < min_points_) continue;

      double sum = 0.0;
      std::vector<double> velocities;
      velocities.reserve(j - i);
      for (size_t k = i; k < j; ++k) {
        sum += hits[k].range;
        velocities.push_back(hits[k].velocity);
      }
      std::sort(velocities.begin(), velocities.end());
      range = sum / static_cast<double>(j - i);
      raw_velocity = velocities[velocities.size() / 2];
      found = true;
      break;
    }

    const double t = stamp > 0.0 ? stamp : simNow();
    const bool recently_tracked = have_target_ && last_target_sim_ >= 0.0 &&
        t >= last_target_sim_ && t - last_target_sim_ < 0.40;

    if (found) {
      // Don't jump immediately to a much farther reflection if the
      // currently tracked car briefly becomes hard to see.
      if (!(recently_tracked && range > target_range_ + 5.0)) {
        if (recently_tracked) {
          const double a = range < target_range_ ? 0.80 : 0.35;
          target_range_ += a * (range - target_range_);
          target_velocity_ += 0.50 * (raw_velocity - target_velocity_);
        } else {
          target_range_ = range;
          target_velocity_ = raw_velocity;
        }
        have_target_ = true;
        last_target_sim_ = t;
      }
    }

    publishControl();  // Act on each radar frame immediately.
  }

  void publishControl() {
    const size_t subscribers = control_pub_->get_subscription_count();
    if (subscribers != last_control_subscribers_) {
      RCLCPP_INFO(get_logger(), "Control subscribers: %zu -> %zu",
                  last_control_subscribers_, subscribers);
      // A loss of a subscriber can indicate Scenic destroying the ego.
      // Never clear a working target simply because a subscriber appeared.
      if (subscribers < last_control_subscribers_) {
        resetEpisode("control subscriber disappeared");
      }
      last_control_subscribers_ = subscribers;
    }

    // Detect clock rewinds using the raw /clock time (before compensating
    // for radar headers which might be one simulation frame ahead).
    const double raw_clock = get_clock()->now().seconds();
    if (raw_clock > 0.0 && last_raw_clock_ > 0.0 &&
        raw_clock < last_raw_clock_ - 0.05) {
      resetEpisode("/clock went backwards");
    }
    if (raw_clock > 0.0) last_raw_clock_ = raw_clock;
    const double t = simNow();

    double dt_sim = 0.0;
    if (t > 0.0 && last_control_sim_ >= 0.0 && t >= last_control_sim_) {
      dt_sim = std::clamp(t - last_control_sim_, 0.0, 0.10);
    }
    if (t > 0.0) last_control_sim_ = t;

    const bool radar_sim_stale = have_radar_ && t > 0.0 &&
        last_radar_stamp_ > 0.0 &&
        t - last_radar_stamp_ > 0.35;
    const bool radar_wall_stale = have_radar_ &&
        last_radar_wall_ != WallClock::time_point{} &&
        WallClock::now() - last_radar_wall_ > 1500ms;

    const bool target_fresh = have_target_ && last_target_sim_ >= 0.0 &&
        t >= last_target_sim_ && t - last_target_sim_ < 0.30;
    const bool recently_lost_close = have_target_ && !target_fresh &&
        last_target_sim_ >= 0.0 && t >= last_target_sim_ &&
        t - last_target_sim_ < 0.90 && target_range_ < 35.0;

    double want_throttle = 0.0;
    double want_brake = 0.0;
    double safe_gap = gap_;
    const char *state = "CLEAR";

    if (!have_radar_) {
      // Only for this simulated demo: move before sensor data arrives.
      want_throttle = startup_throttle_;
      state = "STARTUP";
    } else if (radar_sim_stale || radar_wall_stale) {
      want_brake = 1.0;
      state = "RADAR STALE";
    } else if (nearest_ < gap_ + 2.0) {
      // A single very close forward return should force a stop.
      want_brake = 1.0;
      state = "EMERGENCY";
    } else if (target_fresh) {
      // CARLA's radar source projects (target_velocity - ego_velocity)
      // onto the outward ray. NEGATIVE velocity = approaching object.
      const double closing = std::clamp(-target_velocity_, 0.0, 30.0);

      // Final desired gap + anticipation + relative braking distance.
      // Uses SIMULATED m/s and m/s^2, independent of wall-time speed.
      safe_gap = gap_ + closing * 0.90 + closing * closing / 9.0;
      const double error = target_range_ - safe_gap;

      if (target_range_ <= gap_ + 2.0) {
        want_brake = 1.0;
        state = "HOLD";
      } else if (error <= 0.0) {
        want_brake = std::clamp(0.60 - error * 0.08, 0.60, 1.0);
        state = "BRAKE";
      } else if (error < 6.0) {
        want_brake = 0.45 * (6.0 - error) / 6.0;
        state = "SLOW";
      } else {
        want_throttle = std::min(max_throttle_,
                                 0.20 + 0.035 * (error - 6.0));
        state = "FOLLOW";
      }
    } else if (recently_lost_close) {
      want_brake = 0.65;
      state = "TARGET LOST";
    } else {
      want_throttle = cruise_throttle_;
      state = "CLEAR";
    }

    // All pedal-rate calculations use elapsed SIMULATION seconds.
    // Brakes apply immediately; throttle rises more gradually.
    if (want_brake > 0.0) {
      throttle_ = 0.0;
      brake_ = std::max(want_brake, brake_ - 10.0 * dt_sim);
    } else if (!have_radar_) {
      // /clock may still be zero at startup. Don't let dt_sim=0 block
      // the initial throttle commands.
      throttle_ = startup_throttle_;
      brake_ = 0.0;
    } else {
      brake_ = std::max(0.0, brake_ - 10.0 * dt_sim);
      if (brake_ < 0.01) {
        brake_ = 0.0;
        if (want_throttle > throttle_) {
          throttle_ = std::min(want_throttle, throttle_ + 3.0 * dt_sim);
        } else {
          throttle_ = std::max(want_throttle, throttle_ - 8.0 * dt_sim);
        }
      } else {
        throttle_ = 0.0;
      }
    }

    carla_msgs::msg::CarlaEgoVehicleControl cmd;
    cmd.header.stamp = now();
    cmd.throttle = static_cast<float>(std::clamp(throttle_, 0.0, 1.0));
    cmd.brake = static_cast<float>(std::clamp(brake_, 0.0, 1.0));
    cmd.steer = 0.0f;
    cmd.hand_brake = false;
    cmd.reverse = false;
    cmd.manual_gear_shift = false;
    control_pub_->publish(cmd);

    RCLCPP_INFO_THROTTLE(
        get_logger(), log_clock_, 500,
        "%s | sim=%.2f | range=%.1f m | closing=%.1f m/s | "
        "safe=%.1f m | throttle=%.2f | brake=%.2f",
        state, t, target_range_, -target_velocity_, safe_gap,
        cmd.throttle, cmd.brake);
  }

  double gap_ = 5.0;
  double half_width_ = 1.4;
  double cruise_throttle_ = 0.45;
  double startup_throttle_ = 0.35;
  double max_throttle_ = 0.65;
  int min_points_ = 2;

  size_t last_control_subscribers_ = 0;
  bool have_radar_ = false;
  bool have_target_ = false;
  double target_range_ = 0.0;
  double target_velocity_ = 0.0;
  double nearest_ = std::numeric_limits<double>::infinity();
  double last_radar_stamp_ = 0.0;
  double last_target_sim_ = -1.0;
  double last_control_sim_ = -1.0;
  double last_raw_clock_ = 0.0;
  double throttle_ = 0.0;
  double brake_ = 0.0;

  WallClock::time_point last_radar_wall_{};
  rclcpp::Clock log_clock_{RCL_STEADY_TIME};

  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr radar_sub_;
  rclcpp::Publisher<carla_msgs::msg::CarlaEgoVehicleControl>::SharedPtr control_pub_;
  rclcpp::TimerBase::SharedPtr sim_timer_;
  rclcpp::TimerBase::SharedPtr wall_timer_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<RadarFollower>());
  rclcpp::shutdown();
  return 0;
}
