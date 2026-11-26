import json
import os
import shutil
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scenicecocar.tools.ego_config_parser import GenericSensor

CARLA_SENSOR_TOPICS: dict[str, list[tuple[str, str]]] = {
    "sensor.camera.rgb": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.depth": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.semantic_segmentation": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.instance_segmentation": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.normals": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.optical_flow": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.dvs": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
        ("point_cloud", "sensor_msgs/msg/PointCloud2"),
    ],
    "sensor.camera.cosmos_visualization": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.rgb.wide_angle_lens": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.depth.wide_angle_lens": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.normals.wide_angle_lens": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.semantic_segmentation.wide_angle_lens": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.camera.instance_segmentation.wide_angle_lens": [
        ("image", "sensor_msgs/msg/Image"),
        ("camera_info", "sensor_msgs/msg/CameraInfo"),
    ],
    "sensor.lidar.ray_cast": [
        ("point_cloud", "sensor_msgs/msg/PointCloud2"),
    ],
    "sensor.lidar.ray_cast_semantic": [
        ("point_cloud", "sensor_msgs/msg/PointCloud2"),
    ],
    "sensor.lidar.hss_lidar": [
        ("point_cloud", "sensor_msgs/msg/PointCloud2"),
    ],
    "sensor.other.radar": [
        ("point_cloud", "sensor_msgs/msg/PointCloud2"),
    ],
    "sensor.other.gnss": [
        ("", "sensor_msgs/msg/NavSatFix"),
    ],
    "sensor.other.imu": [
        ("", "sensor_msgs/msg/Imu"),
    ],
    "sensor.other.collision": [
        ("", "carla_msgs/msg/CarlaCollisionEvent"),
    ],

    # No implemented native ROS 2 data publisher
    "sensor.other.lane_invasion": [],
    "sensor.other.obstacle": [],
    "sensor.other.rss": [],
    "sensor.other.v2x": [],
    "sensor.other.v2x_custom": [],
}


class ROSRecorder:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _post(self, endpoint, payload = None):
        request = Request(
            self.url + endpoint,
            data = json.dumps(payload or {}).encode(),
            headers = {"Content-Type": "application/json"},
            method = "POST",
        )

        try:
            with urlopen(request, timeout = 60) as response:
                return json.load(response)
        except HTTPError as E:
            raise RuntimeError(E.read().decode()) from E

    def precreate_sensor_topics(self, sensors: list[GenericSensor], parent_name: str = "hero"):
        topics = {}
        channel_count = 0

        for sensor in sensors:
            if sensor.blueprint not in CARLA_SENSOR_TOPICS:
                continue

            base = f"/carla/{parent_name}/{sensor.name}"

            for (sufix, topic_format) in CARLA_SENSOR_TOPICS[sensor.blueprint]:
                full_topic = base if sufix == "" else f"{base}/{sufix}"
                topics[full_topic] = topic_format

                channel_count += 1

        if channel_count > 0:
            return self._post("/configure", topics)

    def start(self):
        return self._post("/start")

    def stop(self):
        return self._post("/stop")

    def keep_alive_ping(self):
        return self._post("/keep_alive")

    def status(self):
        with urlopen(self.url + "/status", timeout = 10) as response:
            return json.load(response)

    def save(self, path: str):
        with urlopen(self.url + "/recording", timeout = 120) as response:
            with open(path, "wb") as file:
                shutil.copyfileobj(response, file, length = 1024 * 1024)

            size = response.headers.get("Content-Length")

            if size is not None and os.path.getsize(path) != int(size):
                raise IOError("Incomplete MCAP download")
