import copy
from datetime import datetime
import json
import math
import os
import shutil
import sys
import time
import scenic
import dill
import argparse
import logging
import scenic.core
import scenic.core.errors as errors
import scenic.core.scenarios
import scenic.syntax.translator as translator
from scenic.core.errors import InvalidScenarioError

from scenicecocar.tools.ego_config_parser import parse_ego_config
from scenicecocar.tools.utility import SimulationResultType, format_time, is_failed_type, is_passed_type, run_simulation

logger = logging.getLogger(__name__)

def validateTestRecords(scenerio: scenic.core.scenarios.Scenario) -> bool:
    failed_seen = set()
    passed_seen = set()

    for record in scenerio.recordedFinalExprs:
        if is_passed_type(record.name) == True:
            if record.name in passed_seen:
                raise InvalidScenarioError(f"Only one `{record.name}` record final is allowed")
            passed_seen.add(record.name)

        if is_failed_type(record.name) == True:
            if record.name in failed_seen:
                raise InvalidScenarioError(f"Only one `{record.name}` record final is allowed")
            failed_seen.add(record.name)
    
    if len(passed_seen) == 0:
        raise InvalidScenarioError("A `PASSED` record final is required")
    
    for record in scenerio.recordedExprs:
        if is_passed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record can only be a record final")

        if is_failed_type(record.name) == True:
            if record.name in failed_seen:
                raise InvalidScenarioError(f"Only one `{record.name}` record is allowed")
            failed_seen.add(record.name)

    for record in scenerio.recordedInitialExprs:
        if is_passed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record can only be a record final")

        if is_failed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record cannot be a record initial")
        
    return True

def run_command(args: argparse.Namespace) -> int:
    params = {}
    for name, value in args.param:
        # Convert params to ints or floats if possible
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass

        logging.debug(f"Parsed param {name} as {value} ({type(value)})")
        params[name] = value

    start_time = time.time()
    logging.info("Beginning scenario construction")

    scenario = errors.callBeginningScenicTrace(
        lambda: translator.scenarioFromFile(
            args.scenic_file,
            params=params,
            scenario=args.scenario,
            mode2D=True,
        )
    )

    errors.callBeginningScenicTrace(
        lambda: validateTestRecords(scenario)
    )

    total_time = time.time() - start_time
    logging.info(f"Scenario constructed in {total_time:.2f} seconds")

    logging.info("Connecting to simulator")
    simulator = errors.callBeginningScenicTrace(
        scenario.getSimulator
    )

    simulator.render = args.render

    ego_car_sensors = []
    if args.ego_car_config:
        ego_car_sensors = parse_ego_config(args.ego_car_config)

    logging.info(f"Simulator connected and configured")

    try:
        if args.save_scenes:

            run_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            if args.run_name is not None:
                run_name = args.run_name.strip()

            base_folder_name = os.path.join(args.save_dir, run_name)
            logging.info(f"Saving initial run data at {base_folder_name}")

            os.makedirs(base_folder_name)

            shutil.copy2(args.scenic_file, os.path.join(base_folder_name, "scenario.scenic"))

            if args.ego_car_config:
                shutil.copy2(args.ego_car_config, os.path.join(base_folder_name, "ego_config.yaml"))

            metadata = {
                "original_scenario_path": os.path.abspath(args.scenic_file),
                "command": sys.argv.copy()
            }

            with open(os.path.join(base_folder_name, "scenerio.bin"), "wb") as file:
                dill.dump(scenario, file)

            logging.info(f"Saved initial run data ")

    
        logging.info("Beginning scene generation and simulation")

        loop_start_time = time.time()

        scene_count = 0
        generation_success_count = 0

        passed_count = 0
        failed_count = 0
        invalid_count = 0

        scene_results = []
        while True:
            scene_count += 1

            start_time = time.time()
            logging.debug(f"Generating scene {scene_count}")

            scene, iterations = errors.callBeginningScenicTrace(
                lambda: scenario.generate(maxIterations=2000, verbosity=args.verbosity)
            )

            scene.egoObject.rolename = "hero"

            for sensor in ego_car_sensors:
                scene.egoObject.sensors[sensor.name] = copy.deepcopy(sensor)

            scene_data = scenario.sceneToBytes(scene)

            generation_total_time = time.time() - start_time
            logging.debug(f"Generated scene {scene_count} in {iterations} iterations and {generation_total_time:.4g} seconds")

            if args.save_scenes:
                logging.debug(f"Saving latest generated scene")

                with open(os.path.join(base_folder_name, "latest.bin"), "wb") as file:
                    file.write(scene_data)

                logging.debug(f"Saved latest generated scene")

            start_time = time.time()
            logging.debug(f"Beginning scene simulation for scene {scene_count}")

            simulation_result, passed_records, failed_records = run_simulation(
                simulator,
                scene,
                max_steps = None,
                name = str(scene_count),
                verbosity = args.verbosity,
                max_iterations = 1,
                rtf = args.rtf
            )

            simulation_total_time = time.time() - start_time
            logging.debug(f"Ran simulation for scene {scene_count} in {simulation_total_time:.4g} seconds")

            if simulation_result != SimulationResultType.INVALID:
                generation_success_count += 1
                if simulation_result == SimulationResultType.PASSED:
                    passed_count += 1
                else:
                    failed_count += 1
            else:
                invalid_count += 1

            scene_saved = args.save_scenes == True and simulation_result.name.lower() in args.save_groups

            scene_results.append(
                {
                    "scene": scene_count,
                    "result": simulation_result.name,
                    "passed_records": passed_records,
                    "failed_records": failed_records,
                    "generation_time": generation_total_time,
                    "simulation_time": simulation_total_time,
                    "scene_saved": scene_saved,
                }
            )

            if scene_saved:
                logging.debug(f"Scene {scene_count} returned {simulation_result.name} which is in save-groups. Saving scene")

                save_folder = os.path.join(base_folder_name, f"scene_{scene_count}/")

                os.mkdir(save_folder)

                with open(os.path.join(save_folder, "scene.bin"), "wb") as file:
                    file.write(scene_data)

                logging.debug(f"Saved scene {scene_count} at {save_folder}")

            if args.save_scenes:
                logging.debug("Saving updated run metadata")

                metadata["scenes"] = scene_results
                json.dump(
                    metadata,
                    open(os.path.join(base_folder_name, "metadata.json"), "w"),
                    indent=4
                )

                logging.debug("Saved updated run metadata")

            progresses = []
            remaining_time = math.inf
            if "count" in args.stop_conditions:
                progresses.append(f"{generation_success_count}/{args.count}")
                remaining_time = ((time.time() - loop_start_time) / scene_count) * (args.count - generation_success_count)
            if "duration" in args.stop_conditions:
                progresses.append(f"{format_time(time.time() - loop_start_time)}/{format_time(args.duration)}")
                remaining_time = min(
                    remaining_time,
                    (loop_start_time + args.duration) - time.time()
                )

            remaining_text = f" | ETA {format_time(max(0, remaining_time))}" if math.isfinite(remaining_time) else ""
                
            logging.info(
                f"[{', '.join(progresses)}] Scene {scene_count:03d} | {simulation_result.name} | P = {passed_count:03d} F = {failed_count:03d} I = {invalid_count:03d}{remaining_text}"
            )

            if "first-failed" in args.stop_conditions and simulation_result == SimulationResultType.FAILED:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-failed'")
                break
            if "first-passed" in args.stop_conditions and simulation_result == SimulationResultType.PASSED:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-passed'")
                break
            if "first-invalid" in args.stop_conditions and simulation_result == SimulationResultType.INVALID:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-invalid'")
                break

            if "count" in args.stop_conditions:
                if generation_success_count >= args.count:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'count' with varient successful generations")
                    break
                elif scene_count >= args.count * 10:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'count' with variant total generations")
                    break

            if "duration" in args.stop_conditions:
                spent_time = time.time() - loop_start_time
                
                if spent_time >= args.duration:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'duration'")
                    break

        logging.info("")

        valid_scenes = 0
        passed_scenes = 0
        for scene_data in scene_results:
            if scene_data["result"] != SimulationResultType.INVALID.name:
                valid_scenes += 1

                if scene_data["result"] == SimulationResultType.PASSED.name:
                    passed_scenes += 1

        if valid_scenes > 0:
            passed_rate = (passed_scenes / valid_scenes) * 100
            failed_rate = 100 - passed_rate
        else:
            passed_rate = 0.0
            failed_rate = 0.0

        report_text = [
            "=" * 40,
            "Scenic Test Report",
            "=" * 40,
            "",
            f"Scenario: {args.scenic_file}",
            f"Save Scenes: {args.save_scenes}",
        ]

        if args.save_scenes == True:
            report_text.append(f"Save Location: {base_folder_name}")
            report_text.append(f"Save Groups: [{', '.join(args.save_groups)}]")

        report_text += [
            f"Stop Conditions: [{', '.join(args.stop_conditions)}]",
        ]

        if args.count > 0:
            report_text.append(f"Count: {args.count}")
        if args.duration > 0:
            report_text.append(f"Duration: {args.duration}")

        report_text += [
            f"Total Generated: {scene_count}",
            "",
            f"Passed: {passed_scenes} ({passed_rate:.1f}%)",
            f"Failed: {valid_scenes - passed_scenes} ({failed_rate:.1f}%)",
            f"Invalid: {scene_count - valid_scenes}",
            "",
            "Scenes:"
        ]

        for item in scene_results:
            if args.filter_report and item['result'].lower() not in args.report_groups:
                continue

            if args.detailed_report == True:
                report_text += [
                    f"  Scene {item['scene']:03d}:",
                    f"    Result: {item['result']}",
                    f"    Saved: {item['scene_saved']}",
                    f"    Passed Records: [{', '.join(item['passed_records'])}]",
                    f"    Failed Records: [{', '.join(item['failed_records'])}]"
                ]
            else:
                report_text.append(f"  Scene {item['scene']:03d} - {item['result']}")            

        for line in report_text:
            logging.info(line)

        if args.save_scenes:
            logging.debug("Saving run metadata")

            metadata["scenes"] = scene_results
            json.dump(
                metadata,
                open(os.path.join(base_folder_name, "metadata.json"), "w"),
                indent=4
            )

            with open(os.path.join(base_folder_name, "report.txt"), "w") as file:
                file.write("\n".join(report_text))

            logging.debug("Saved run metadata")

        if "count" in args.stop_conditions and scene_count >= args.count * 10:
            return 1
    
        if passed_scenes != valid_scenes or valid_scenes == 0:
            return 1
    
        return 0 
    except KeyboardInterrupt:
        pass
    finally:
        simulator.destroy()

    return 2
    