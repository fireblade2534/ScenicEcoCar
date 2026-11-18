import carla
import yaml
import scenic.core.sensors

class GenericSensor(scenic.core.sensors.Sensor):
    def __init__(
        self,
        name: str,
        type: str,
        offset: list[float],
        rotation: list[float],
        attributes: dict[str, str]
    ):
        self.name = name
        self.blueprint = type
        self.offset = offset
        self.rotation = rotation
        self.attributes = attributes

        self.attributes["ros_name"] = name
        self.attributes["ros_role"] = name

        self.convert = None
        self.carla_sensor = None
        self.frame = 0

    def onData(self, data):
        self.frame = data.frame

    def getObservation(self):
        return None

def parse_ego_config(path: str) -> list[GenericSensor]:
    with open(path, "r", encoding="utf-8") as file:
        ego_config = yaml.safe_load(file)

    generic_sensors = []

    if "sensors" in ego_config:
        for sensor_name, sensor_config in ego_config["sensors"].items():
            position = sensor_config["transform"]["position"]
            rotation = sensor_config["transform"]["rotation"]

            generic_sensors.append(GenericSensor(
                sensor_name,
                sensor_config["type"],
                offset = [
                    float(position.get("x", 0.0)),
                    float(position.get("y", 0.0)),
                    float(position.get("z", 0.0))
                ],
                rotation = [
                    float(rotation.get("yaw", 0.0)), # Invert yaw and pitch to compensate for scenic inverting yaw and pitch
                    float(rotation.get("pitch", 0.0)),
                    float(rotation.get("roll", 0.0))
                ],
                attributes = sensor_config.get("attributes", {})
            ))

    return generic_sensors

