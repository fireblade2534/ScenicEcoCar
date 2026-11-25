import json
import struct
import threading

from mcap.writer import Writer
from websockets.sync.client import connect

class FoxgloveRecorder:
    def __init__(self, url: str, output_path: str) -> None:
        self.url = url
        self.output_path = output_path

        self._channels = {}
        self._subscriptions = {}
        self._next_id = 0

        self._stop = threading.Event()
        self._thread = None
        self._error = None

    def start(self) -> None:
        self._stop.clear()

        self._thread = threading.Thread(
            target = self._record
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

        if self._thread:
            self._thread.join(timeout = 10.0)

            if self._thread.is_alive():
                raise RuntimeError(
                    "Recording thread is alive after stop timeout"
                )
    
    def _record(self) -> None:
        with connect(
            self.url,
            subprotocols = ["foxglove.websocket.v1", "foxglove.sdk.v1"],
            max_size = None,
            open_timeout = 5,
            close_timeout = 2
        ) as ws, open(self.output_path, "wb") as file:
            writer = Writer(file)
            writer.start()

            self._channels = {}
            self._subscriptions = {}

            self._next_id = 0

            clock_id = -1
            clocked = False
            
            try:
                while not self._stop.is_set():
                    try:
                        msg = ws.recv(timeout=0.2)
                    except TimeoutError:
                        continue

                    if isinstance(msg, str):
                        event = json.loads(msg)

                        if event["op"] == "advertise":
                            new_subs = []
                
                            for channel in event["channels"]:
                                channel_id = channel["id"]
                
                                if channel_id in self._channels:
                                    continue
                
                                if channel["encoding"] != "cdr":
                                    continue
                
                                schema_id = writer.register_schema(
                                    name = channel["schemaName"],
                                    encoding = channel.get(
                                        "schemaEncoding",
                                        "ros2msg",
                                    ),
                                    data = channel["schema"].encode(),
                                )
                
                                mcap_id = writer.register_channel(
                                    topic = channel["topic"],
                                    message_encoding = "cdr",
                                    schema_id = schema_id,
                                )
                
                                self._channels[channel_id] = self._next_id
                                self._subscriptions[self._next_id] = mcap_id
                
                                new_subs.append({
                                    "id": self._next_id,
                                    "channelId": channel_id,
                                })

                                if channel["topic"] == "/clock":
                                    clock_id = self._next_id
                
                                self._next_id += 1
                
                            if new_subs:
                                ws.send(json.dumps({
                                    "op": "subscribe",
                                    "subscriptions": new_subs
                                }))
                
                        elif event["op"] == "unadvertise":
                            for channel_id in event["channelIds"]:
                                subscription_id = self._channels.pop(channel_id, None)
                                if subscription_id is not None:
                                    self._subscriptions.pop(subscription_id, None)

                    elif len(msg) >= 13 and msg[0] == 1:
                        _, subscription_id, timestamp = struct.unpack_from(
                            "<BIQ", msg
                        )

                        if subscription_id not in self._subscriptions:
                            continue

                        if subscription_id == clock_id:
                            clocked = True

                        if not clocked:
                            continue

                        writer.add_message(
                            channel_id = self._subscriptions[subscription_id],
                            log_time = timestamp,
                            publish_time = timestamp,
                            data = msg[13:],
                        )
            finally:
                writer.finish()