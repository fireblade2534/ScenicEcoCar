import copy
import os
import time
import dill
import scenic
import argparse
import scenic.core.errors as errors
import logging
from scenicecocar.tools.ego_config_parser import parse_ego_config
from scenicecocar.tools.replay_fix import repair_scenario_globals
from scenicecocar.tools.utility import SimulationResultType, run_simulation

logger = logging.getLogger(__name__)

def rerun_command(args: argparse.Namespace) -> int:
    start_time = time.time()
    logging.info("Beginning scenario loading")

    with open(os.path.join(args.scene_dir, "scenerio.bin"), "rb") as file:
        scenario = dill.load(file)

    # Fix globals being loaded as seperate items instead of linked items
    repair_scenario_globals(scenario)

    total_time = time.time() - start_time
    logging.info(f"Scenario loaded in {total_time:.2f} seconds")

    logging.info("Connecting to simulator")
    simulator = errors.callBeginningScenicTrace(
        scenario.getSimulator
    )

    simulator.render = args.render

    ego_car_sensors = []
    ego_config_path = os.path.join(args.scene_dir, "ego_config.yaml")
    if os.path.isfile(ego_config_path):
        ego_car_sensors = parse_ego_config(ego_config_path)

    logging.info(f"Simulator connected and configured")

    generation_success_count = 0

    scene_results = []
    for scene_count in args.scenes:
        logging.info(f"Starting loading and simulation for scene {scene_count}")

        start_time = time.time()
        logging.debug(f"Loading scene {scene_count}")
        with open(os.path.join(args.scene_dir, f"scene_{scene_count}/scene.bin"), "rb") as file:
            scene = scenario.sceneFromBytes(file.read())

        scene.egoObject.rolename = "hero"
            
        for sensor in ego_car_sensors:
            scene.egoObject.sensors[sensor.name] = copy.deepcopy(sensor)

        total_time = time.time() - start_time
        logging.debug(f"Loaded scene {scene_count} in {total_time:.4g} seconds")

        start_time = time.time()
        logging.debug(f"Beginning scene simulation for scene {scene_count}")

        simulation_result, passed_records, failed_records  = run_simulation(
            simulator,
            scene,
            max_steps = None,
            name = str(scene_count),
            verbosity = args.verbosity,
            max_iterations = 1
        )

        total_time = time.time() - start_time
        logging.debug(f"Ran simulation for scene {scene_count} in {total_time:.4g} seconds")

        if simulation_result != SimulationResultType.INVALID:
            generation_success_count += 1

        scene_results.append(
            {
                "scene": scene_count,
                "result": simulation_result.name,
                "passed_records": passed_records,
                "failed_records": failed_records,
                "scene_saved": False,
            }
        )
    
    valid_scenes = 0
    passed_scenes = 0
    for scene_data in scene_results:
        if scene_data["result"] != SimulationResultType.INVALID.name:
            valid_scenes += 1

            if scene_data["result"] == SimulationResultType.PASSED.name:
                passed_scenes += 1

    passed_rate = (passed_scenes / valid_scenes) * 100

    report_text = [
        "=" * 40,
        "Scenic Test Report",
        "=" * 40,
        "",
        f"Scenario: {args.scene_dir}",
        f"Total Generated: {len(args.scenes)}",
        "",
        f"Passed: {passed_scenes} ({passed_rate:.1f}%)",
        f"Failed: {valid_scenes - passed_scenes} ({(100 - passed_rate):.1f}%)",
        f"Invalid: {len(args.scenes) - valid_scenes}",
        "",
        "Scenes:"
    ]

    for item in scene_results:
        if args.detailed_report == True:
            report_text += [
                f"  Scene {item['scene']}:",
                f"    Result: {item['result']}",
                f"    Passed Records: [{', '.join(item['passed_records'])}]",
                f"    Failed Records: [{', '.join(item['failed_records'])}]"
            ]
        else:
            report_text.append(f"  Scene {item['scene']} - {item['result']}")

    for line in report_text:
        logging.info(line)

    if valid_scenes != passed_scenes:
        return 1

    return 0