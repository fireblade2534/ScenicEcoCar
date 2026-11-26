FROM osrf/ros:kilted-desktop

SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-colcon-common-extensions \
    python3-rosdep \
    git \
    build-essential \
    ros-kilted-rosidl-default-generators \
    ros-kilted-rosidl-default-runtime \
    ros-kilted-ros-environment \
    ros-kilted-ament-cmake \
    ros-kilted-builtin-interfaces \
    ros-kilted-std-msgs \
    ros-kilted-vision-msgs \
    ros-kilted-geometry-msgs \
    ros-kilted-diagnostic-msgs \
    ros-kilted-foxglove-bridge \
    ros-kilted-rosbag2 \
    ros-kilted-rosbag2-py \
    ros-kilted-rosbag2-storage-mcap \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/carla_ws/src
RUN git clone https://github.com/carla-simulator/ros-carla-msgs.git

WORKDIR /opt/carla_ws

RUN source /opt/ros/kilted/setup.bash && \
    colcon build --packages-select carla_msgs

RUN for user_home in /root /home/ubuntu; do \
    printf '%s\n' \
        'source /opt/ros/kilted/setup.bash' \
        'source /opt/carla_ws/install/setup.bash' \
        'if [ -f /workspace/install/setup.bash ]; then' \
        '    source /workspace/install/setup.bash' \
        'fi' \
        >> "$user_home/.bashrc"; \
    done

COPY base_entrypoint.sh /usr/local/bin/base_entrypoint.sh
COPY ros_entrypoint.sh /usr/local/bin/ros_entrypoint.sh

RUN chmod +x /usr/local/bin/base_entrypoint.sh
RUN chmod +x /usr/local/bin/ros_entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/bin/bash", "/usr/local/bin/ros_entrypoint.sh"]
CMD ["ros2", "run", "carla_control", "radar_follower"]