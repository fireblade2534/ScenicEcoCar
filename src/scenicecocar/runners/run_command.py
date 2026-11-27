import copy
from datetime import datetime
import json
import math
import os
import shutil
import sys
import threading
import time
import scenic
import dill
import argparse
import logging
import scenic.core
import scenic.core.errors as errors
import scenic.core.scenarios
import scenic.syntax.translator as translator

from scenicecocar.recorders.native_ros import ROSRecorder
from scenicecocar.tools.ego_config_parser import parse_ego_config
from scenicecocar.tools.utility import SimulationResultType, format_time, run_simulation, validateTestRecords

logger = logging.getLogger(__name__)

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

    # Construct the scenerio from the scenic file
    scenario = errors.callBeginningScenicTrace(
        lambda: translator.scenarioFromFile(
            args.scenic_file,
            params=params,
            scenario=args.scenario,
            mode2D=True,
        )
    )

    # Validate if the scenic file has passed and optionally failed records
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

    # Parse the ego car config
    ego_car_sensors = []
    if args.ego_car_config:
        ego_car_sensors = parse_ego_config(args.ego_car_config)

    logging.info(f"Simulator connected and configured")

    try:
        # Create the folder structure and save inital files if saving scenes is enabled
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

            # Dump the scenerio object as it is needed for reruns
            with open(os.path.join(base_folder_name, "scenerio.bin"), "wb") as file:
                dill.dump(scenario, file)

            logging.info(f"Saved initial run data ")

        if args.record_ros2:
            recorder = ROSRecorder(
                url = args.record_url,
            )

            # Precreate sensor topics so that we don't miss any inital data in the simulation caused by it taking time to discover new topics
            recorder.precreate_sensor_topics(ego_car_sensors, parent_name = "hero")

    
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

            # Ensure the ego car has the rolename hero and add our ego car sensors to the list of sensors managed by scenic
            scene.egoObject.rolename = "hero"
            for sensor in ego_car_sensors:
                scene.egoObject.sensors[sensor.name] = copy.deepcopy(sensor)

            scene_raw_data = scenario.sceneToBytes(scene)

            generation_total_time = time.time() - start_time
            logging.debug(f"Generated scene {scene_count} in {iterations} iterations and {generation_total_time:.4g} seconds")

            if args.save_scenes:
                logging.debug(f"Saving latest generated scene")

                # To rerun a specific scene we also need to save data that specifies any random values
                with open(os.path.join(base_folder_name, "latest.bin"), "wb") as file:
                    file.write(scene_raw_data)

                logging.debug(f"Saved latest generated scene")

            start_time = time.time()
            logging.debug(f"Beginning scene simulation for scene {scene_count}")

            try:
                # Start the ros recorder
                if args.record_ros2:
                    # Start a keep alive thread that must be pinging the recorder to prevent it from automatically stoping the recording
                    stop = threading.Event()
                    def keep_alive():
                        while not stop.wait(2):
                            recorder.keep_alive_ping()
                    threading.Thread(target = keep_alive, daemon = True).start()

                    # Start the actual recorder
                    recorder.start()

                simulation_result, passed_records, failed_records = run_simulation(
                    simulator,
                    scene,
                    max_steps = None,
                    name = str(scene_count),
                    verbosity = args.verbosity,
                    max_iterations = 1,
                    rtf = args.rtf
                )
            finally:
                if args.record_ros2:
                    # Stop the keep alive thread and the recorder
                    stop.set()
                    recorder.stop()

            simulation_total_time = time.time() - start_time
            logging.debug(f"Ran simulation for scene {scene_count} in {simulation_total_time:.4g} seconds")

            # Update the simulation counts
            if simulation_result != SimulationResultType.INVALID:
                generation_success_count += 1
                if simulation_result == SimulationResultType.PASSED:
                    passed_count += 1
                else:
                    failed_count += 1
            else:
                invalid_count += 1

            scene_saved = args.save_scenes == True and simulation_result.name.lower() in args.save_groups

            # Update metadata
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
                    file.write(scene_raw_data)

                # Get and save the mcap file from the ros recorder
                if args.record_ros2:
                    recorder.save(os.path.join(save_folder, "scene.mcap"))

                logging.debug(f"Saved scene {scene_count} at {save_folder}")

            # Update the saved metadata for the scene regardless of if the full scene data should be saved
            if args.save_scenes:
                logging.debug("Saving updated run metadata")

                metadata["scenes"] = scene_results
                json.dump(
                    metadata,
                    open(os.path.join(base_folder_name, "metadata.json"), "w"),
                    indent=4
                )

                logging.debug("Saved updated run metadata")

            # Get the completion text for the progress bar and get the minimum of the estimated remaning times
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

            # Check the first-* stop conditions
            if "first-failed" in args.stop_conditions and simulation_result == SimulationResultType.FAILED:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-failed'")
                break
            if "first-passed" in args.stop_conditions and simulation_result == SimulationResultType.PASSED:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-passed'")
                break
            if "first-invalid" in args.stop_conditions and simulation_result == SimulationResultType.INVALID:
                logging.debug(f"Stopping at {scene_count} due to stop condition 'first-invalid'")
                break

            # Check the count stop condition
            if "count" in args.stop_conditions:
                if generation_success_count >= args.count:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'count' with varient successful generations")
                    break
                # Hardcode a limit to the number of both sucessful and unsccessful generations
                elif scene_count >= args.count * 10:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'count' with variant total generations")
                    break

            # Check the duration stop condition
            if "duration" in args.stop_conditions:
                spent_time = time.time() - loop_start_time
                
                if spent_time >= args.duration:
                    logging.debug(f"Stopping at {scene_count} due to stop condition 'duration'")
                    break

        logging.info("")

        valid_count = passed_count + failed_count

        if valid_count > 0:
            passed_rate = (passed_count / valid_count) * 100
            failed_rate = 100 - passed_rate
        else:
            passed_rate = 0.0
            failed_rate = 0.0

        # Construct the report a list of individual lines
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
            f"Passed: {passed_count} ({passed_rate:.1f}%)",
            f"Failed: {failed_count} ({failed_rate:.1f}%)",
            f"Invalid: {scene_count - valid_count}",
            "",
            "Scenes:"
        ]

        # Output either a default 
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

        # Save the final metadata and report text
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
    
        if passed_count != valid_count or valid_count == 0:
            return 1
    
        return 0 
    except KeyboardInterrupt:
        pass
    finally:
        # Make sure to cleanup and stop any recordings
        simulator.destroy()

        if args.record_ros2:
            try:
                recorder.stop()
            except Exception:
                pass

    return 2
    