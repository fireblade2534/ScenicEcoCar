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

  static rclcpp::NodeOptions simOptions() {
    rclcpp::NodeOptions options;
    options.parameter_overrides({rclcpp::Parameter("use_sim_time", true)});
    return options;
  }

public:
  RadarFollower() : Node("radar_follower", simOptions()) {
    gap = std::max(1.0, declare_parameter<double>("target_gap", 5.0));
    gap_p = std::max(0.0, declare_parameter<double>("gap_p", 0.1));
    velocity_p = std::max(0.0, declare_parameter<double>("velocity_p", 0.2));

    const auto radar_topic = declare_parameter<std::string>(
      "radar_topic", "/carla/hero/front_radar/point_cloud");
    const auto control_topic = declare_parameter<std::string>(
      "control_topic", "/carla/hero/vehicle_control_cmd");

    radar_sub = create_subscription<sensor_msgs::msg::PointCloud2>(
      radar_topic, rclcpp::SensorDataQoS(),
      std::bind(&RadarFollower::onRadar, this, std::placeholders::_1)
    );

    control_pub = create_publisher<carla_msgs::msg::CarlaEgoVehicleControl>(
      control_topic, rclcpp::QoS(10).reliable());
  }

private:
  void onRadar(const sensor_msgs::msg::PointCloud2::SharedPtr msg) {
    double closest_center_dist = std::numeric_limits<double>::infinity();
    double best_distance = std::numeric_limits<double>::infinity();
    double best_velocity = std::numeric_limits<double>::infinity();

    sensor_msgs::PointCloud2ConstIterator<float> x(*msg, "x"); // Sensor relative forward/backward
    sensor_msgs::PointCloud2ConstIterator<float> y(*msg, "y"); // Sensor relative left/right
    sensor_msgs::PointCloud2ConstIterator<float> z(*msg, "z"); // Sensor relative up/down
    sensor_msgs::PointCloud2ConstIterator<float> depth(*msg, "depth");
    sensor_msgs::PointCloud2ConstIterator<float> velocity(*msg, "velocity");

    for (; x != x.end(); ++x, ++y, ++z, ++depth, ++velocity) {
      double sensor_plane_distance = (*y * *y) + (*z * *z);
      if (sensor_plane_distance > closest_center_dist) {
        continue;
      }

      closest_center_dist = sensor_plane_distance;
      best_distance = *x;
      best_velocity = *velocity;
    }

    double control_output;
    if (std::isinf(best_distance)) {
      control_output = 0.2;
    } else {
      double distance_error = best_distance - gap;
      double velocity_error = best_velocity;

      control_output = (distance_error * gap_p) + (velocity_error * velocity_p);
    }

    double throttle_output = std::clamp(control_output, 0.0, 1.0);
    double brake_output = std::clamp(-control_output, 0.0, 1.0);

    carla_msgs::msg::CarlaEgoVehicleControl cmd;
    cmd.header.stamp = now();
    cmd.throttle = static_cast<float>(throttle_output);
    cmd.brake = static_cast<float>(brake_output);
    cmd.steer = 0.0f;
    cmd.hand_brake = false;
    cmd.reverse = false;
    cmd.manual_gear_shift = false;
    control_pub->publish(cmd);
  }

  double gap = 5.0;
  double gap_p = 0.1;
  double velocity_p = 0.2;

  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr radar_sub;
  rclcpp::Publisher<carla_msgs::msg::CarlaEgoVehicleControl>::SharedPtr control_pub;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<RadarFollower>());
  rclcpp::shutdown();
  return 0;
}