import json
import os
import shutil
import time
import tempfile
import glob
import threading
from collections import Counter
from functools import partial
from socket import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

import rclpy
import rosbag2_py
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

class Recorder(Node):
    def __init__(self, directory: str, record_timeout: float = 4.0):
        super().__init__("scenic_ros_recorder")
        self.bag_path = os.path.join(directory, "latest")

        self.lock = threading.Lock()

        self.subs = {}
        self.skipped = {}
        self.registered = set()

        self.writer = None
        self.file_complete = False

        self.steady_clock = Clock(clock_type = ClockType.STEADY_TIME)
        self.discover_timer = self.create_timer(0.1, self.discover, clock = self.steady_clock)
        self.keep_alive_timer = self.create_timer(0.2, self.keep_alive, clock = self.steady_clock)

        self.record_timeout = record_timeout
        self.last_keep_alive = time.monotonic()

    def _subscribe(self, topic: str, type_name: str):
        if topic in self.subs:
            if self.subs[topic][0] != type_name:
                raise ValueError(f"Type conflict for {topic}: {type_name}")
            return

        qos = QoSProfile(
            depth = 10,
            reliability = (ReliabilityPolicy.RELIABLE if topic == "/tf_static" else ReliabilityPolicy.BEST_EFFORT),
            durability = (DurabilityPolicy.TRANSIENT_LOCAL if topic == "/tf_static" else DurabilityPolicy.VOLATILE),
        )

        subscription = self.create_subscription(
            get_message(type_name),
            topic,
            partial(self.on_message, topic),
            qos,
            raw = True,
        )
        self.subs[topic] = (type_name, subscription)
        self.skipped.pop(topic, None)
        self.get_logger().info(f"Subscribed: {topic} ({type_name})")

    def configure(self, topics: dict[str, str]):
        with self.lock:
            if self.writer is not None:
                raise ValueError("Cannot configure while recording")
            
            for topic, type_name in topics.items():
                self._subscribe(topic, type_name)

    def keep_alive(self):
        if self.writer is None:
            return
        
        time_diff = time.monotonic() - self.last_keep_alive

        if time_diff > self.record_timeout:
            self.get_logger().warning(f"Keep alive timed out: Stopping recording")
            self.stop_recording()

    def keep_alive_ping(self):
        self.last_keep_alive = time.monotonic()

    def discover(self):
        with self.lock:
            for topic, types in self.get_topic_names_and_types():
                if topic in self.subs or topic in self.skipped:
                    continue
                if len(types) != 1:
                    self.skipped[topic] = f"Ambiguous types: {types}"
                    continue

                try:
                    self._subscribe(topic, types[0])
                except Exception as E:
                    self.skipped[topic] = str(E)
                    self.get_logger().warning(f"Skipping {topic}: {E}")
    
    def start_recording(self):
        with self.lock:
            if self.writer is not None:
                raise ValueError("Already recording")

            self.file_complete = False
            self.keep_alive_ping()

            if os.path.isdir(self.bag_path):
                shutil.rmtree(self.bag_path)

            self.writer = rosbag2_py.SequentialWriter()
            self.writer.open(
                rosbag2_py.StorageOptions(
                    uri = str(self.bag_path),
                    storage_id = "mcap",
                    max_cache_size = 0
                ),
                rosbag2_py.ConverterOptions("cdr", "cdr"),
            )
            self.registered.clear()
    
    def on_message(self, topic: str, data):
        with self.lock:
            if self.writer is None:
                return

            timestamp = self.get_clock().now().nanoseconds

            if topic not in self.registered:
                self.writer.create_topic(
                    rosbag2_py.TopicMetadata(
                        id = 0,
                        name = topic,
                        type = self.subs[topic][0],
                        serialization_format = "cdr",
                    )
                )
                self.registered.add(topic)

            self.writer.write(topic, data, timestamp)
    
    def stop_recording(self):
        with self.lock:
            if self.writer is None:
                raise ValueError("Not recording")

            self.writer.close()
            self.writer = None

            self.file_complete = True

    def status(self):
        with self.lock:
            return {
                "recording": self.writer is not None,
                "file_complete": self.file_complete,
                "topics": {topic: entry[0] for topic, entry in self.subs.items()},
                "skipped": dict(self.skipped),
                "bag_path": str(self.bag_path),
            }

    def completed_file(self) -> str | None:
        with self.lock:
            if not self.file_complete:
                raise ValueError("No finalized recording")

            files = glob.glob(os.path.join(self.bag_path, "*.mcap"))

            if len(files) != 1:
                raise ValueError(f"Expected one MCAP, found {len(files)}")
            
            return files[0]

class Handler(BaseHTTPRequestHandler):
    def __init__(self, request: socket, client_address: tuple[str, int], server: HTTPServer):
        super().__init__(request, client_address, server)

    def reply(self, body, status: int = 200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def do_POST(self):
        node = self.server.recorder
        
        try:
            if self.path == "/configure":
                size = int(self.headers.get("Content-Length", "0"))
                topics = json.loads(self.rfile.read(size))
                node.configure(topics)
                self.reply({"ok": True})

            elif self.path == "/start":
                node.start_recording()
                self.reply({"ok": True})

            elif self.path == "/stop":
                node.stop_recording()
                self.reply({"ok": True})

            elif self.path == "/keep_alive":
                node.keep_alive_ping()
                self.reply({"ok": True})

            else:
                 return self.reply({"error": "Unknown endpoint"}, 404)

        except ValueError as E:
            return self.reply({"error": str(E)}, 409)
        except Exception as E:
            return self.reply({"error": str(E)}, 500)

    def do_GET(self):
        node = self.server.recorder

        try:
            if self.path == "/status":
                return self.reply(node.status())
            
            elif self.path == "/recording":
                path = node.completed_file()
                with open(path, "rb") as file:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(os.path.getsize(path)))
                    self.send_header("Content-Disposition", 'attachment; filename="scene.mcap"')
                    self.end_headers()
                    shutil.copyfileobj(file, self.wfile, length=1024 * 1024)

        except (ValueError, OSError) as E:
            return self.reply({"error": str(E)}, 409)
        except Exception as E:
            return self.reply({"error": str(E)}, 500)

def main():
    rclpy.init()

    with tempfile.TemporaryDirectory(prefix="scenic-ros-") as directory:
        node = Recorder(directory)

        server = HTTPServer(("127.0.0.1", 8769), Handler)
        server.recorder = node
        worker = threading.Thread(target = server.serve_forever, daemon = True)
        worker.start()
        node.get_logger().info(f"Recorder on http://127.0.0.1:8769; bag_path: {node.bag_path}")
        try:
            rclpy.spin(node)
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

            if node.writer is not None:
                node.stop_recording()

            node.destroy_node()
            rclpy.try_shutdown()

if __name__ == "__main__":
    main()