#!/bin/bash
set -eo pipefail

echo "=== Setting up ROS 2 Kilted ==="
source /opt/ros/kilted/setup.bash

echo "=== Setting up CARLA messages ==="
if [ -d /opt/carla_ws/src ]; then
    cd /opt/carla_ws

    if [ ! -f install/setup.bash ]; then
        colcon build --packages-select carla_msgs
    fi

    source /opt/carla_ws/install/setup.bash
fi

cd /workspace
echo "=== Starting Foxglove Bridge ==="
nohup ros2 run foxglove_bridge foxglove_bridge \
    --ros-args \
    -p use_sim_time:=true \
    -p best_effort_qos_topic_whitelist:="['/carla/hero/.*']" \
    > /tmp/foxglove.log 2>&1 < /dev/null &

echo $! > /tmp/foxglove.pid
echo "Foxglove launch PID: $(cat /tmp/foxglove.pid)"


echo "=== Building scenic_recorder ==="
if [ -d /workspace/src/scenic_recorder ]; then
    cd /workspace
    colcon build --symlink-install --packages-select scenic_recorder

    source /workspace/install/setup.bash
fi

echo "=== Starting scenic_recorder ==="
nohup ros2 run scenic_recorder recorder \
    --ros-args \
    -p use_sim_time:=true \
    > /tmp/recorder.log 2>&1 < /dev/null &
echo $! > /tmp/recorder.pid
echo "Recorder launch PID: $(cat /tmp/recorder.pid)"