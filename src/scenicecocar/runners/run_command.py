from datetime import datetime
import json
import os
import shutil
import sys
import time
import scenic
import argparse
import logging
import scenic.core
import scenic.core.errors as errors
import scenic.core.scenarios
import scenic.syntax.translator as translator
from scenic.core.errors import InvalidScenarioError

logger = logging.getLogger(__name__)

def validateTestRecords(scenerio: scenic.core.scenarios.Scenario):
    failed_found = False
    passed_found = False

    for record in scenerio.recordedFinalExprs:
        if record.name == "PASSED":
            if passed_found == True:
                raise InvalidScenarioError("Only one `PASSED` record final is allowed")
            passed_found = True

        if record.name == "FAILED":
            if failed_found == True:
                raise InvalidScenarioError("Only one `FAILED` record final is allowed")
            failed_found = True
    
    if passed_found == False:
        raise InvalidScenarioError("A `PASSED` record final is required")
    
    for record in scenerio.recordedExprs:
        if record.name == "PASSED":
            raise InvalidScenarioError("The `PASSED` record can only be a record final")

        if record.name == "FAILED":
            if failed_found == True:
                raise InvalidScenarioError("Only one `FAILED` record is allowed")
            failed_found = True

    for record in scenerio.recordedInitialExprs:
        if record.name == "PASSED":
            raise InvalidScenarioError("The `PASSED` record can only be a record final")

        if record.name == "FAILED":
            raise InvalidScenarioError("The `FAILED` record cannot be a record initial")
        
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
    logging.info(f"Scenario constructed in {total_time:.2f} seconds.")

    logging.info("Connecting to simulator")
    simulator = errors.callBeginningScenicTrace(
        scenario.getSimulator
    )
    logging.info(f"Simulator connected and configured")

    if args.save_scenes:
        base_folder_name = os.path.join(args.save_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f"))
        logging.info(f"Saving initial run data at {base_folder_name}")

        os.makedirs(base_folder_name)

        shutil.copy2(args.scenic_file, os.path.join(base_folder_name, "scenario.scenic"))

        metadata = {
            "original_scenario_path": os.path.abspath(args.scenic_file),
            "command": sys.argv.copy()
        }

        json.dump(
            metadata,
            open(os.path.join(base_folder_name, "metadata.json"), "w"),
            indent=4
        )

        logging.info(f"Saved initial run data ")


    logging.info("Beginning scene generation and simulation")

    loop_start_time = time.time()

    scene_count = 0
    generation_success_count = 0

    scene_results = []
    while True:
        start_time = time.time()

        logging.debug(f"Generating scene {scene_count}")

        scene, iterations = errors.callBeginningScenicTrace(
            lambda: scenario.generate(maxIterations=2000, verbosity=args.verbosity)
        )

        scene_data = scenario.sceneToBytes(scene)

        total_time = time.time() - start_time
        logging.debug(f"Generated scene {scene_count} in {iterations} iterations and {total_time:.4g} seconds")

        simulation_result = None #TODO

        

    return 0