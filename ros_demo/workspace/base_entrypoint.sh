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
nohup ros2 launch foxglove_bridge foxglove_bridge_launch.xml \
    > /tmp/foxglove.log 2>&1 < /dev/null &

echo $! > /tmp/foxglove.pid
echo "Foxglove launch PID: $(cat /tmp/foxglove.pid)"