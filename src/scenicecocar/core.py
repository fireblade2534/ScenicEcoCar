import json
import os
import sys
import scenic
import argparse
import logging
from scenicecocar.runners.rerun_command import rerun_command
from scenicecocar.runners.run_command import run_command

logger = logging.getLogger(__name__)

def build_parser():
    parser = argparse.ArgumentParser(
        prog = "scenicecocar",
        description = "Scenic scenario testing and replay.",
    )

    common = argparse.ArgumentParser(add_help = False)

    common.add_argument(
        "-v", "--verbosity",
        type = int,
        choices = (0, 1, 2, 3),
        default = 0,
    )

    common.add_argument(
        "--log-level",
        choices = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type = str.upper,
        default = "INFO",
    )


    subparsers = parser.add_subparsers(
        dest = "command",
        required = True,
    )

    run = subparsers.add_parser(
        "run",
        parents = [common],
        help = "Generate and simulate Scenic scenes",
        description = "Run a Scenic testing campaign.",
    )
    run.add_argument(
        "-p",
        "--param",
        help = "override a global parameter",
        nargs = 2,
        default = [],
        action = "append",
        metavar = ("PARAM", "VALUE"),
    )
    run.add_argument(
        "--run-name",
        default = None,
        help = "sets the name of a runs folder (default is date)"
    )
    run.add_argument(
        "--rtf",
        help = "maxium rtf to run the simulation at",
        type = float,
        default = None,
    )
    run.add_argument(
        "--count",
        help = "number of successful scenes to generate or simulations to run (default is infinity)",
        type = int,
        default = 0,
    )
    run.add_argument(
        "--duration",
        help = "duration in seconds to spend generating and simulating as many scenes as possible",
        type = int,
        default = 0,
    )
    run.add_argument(
        "--stop-conditions",
        nargs = "+",
        type = str.lower,
        default = [],
        action = "extend",
        choices = ["count", "first-failed", "first-passed", "first-invalid", "duration"],
        help = "conditions to stop generating and simulating scenes"
    )
    run.add_argument(
        "--save-scenes",
        action = "store_true",
        help = "save scenes for debugging and replay"
    )
    run.add_argument(
        "--save-dir",
        default = "./saved_scenes",
        help = "directory to save scenes for debugging and replay",
        metavar = "DIR"
    )
    run.add_argument(
        "--save-groups",
        nargs = "+",
        type = str.lower,
        default = [],
        action = "extend",
        choices = ["failed", "passed", "invalid"],
        help = "save scenes depending on their status"
    )
    run.add_argument(
        "--record-ros2",
        action = "store_true",
        help = "record ros2",
    )
    run.add_argument(
        "--record-url",
        default = "http://localhost:8769",
        help = "record ros2 url",
        metavar = "FILE"
    )
    run.add_argument(
        "--scenario",
        default = None,
        help = "name of scenario to run (if file contains multiple)"
    )
    run.add_argument(
        "--ego-car-config",
        help = "a yaml file containg the ego cars config",
        metavar = "FILE"
    )
    run.add_argument(
        "--render",
        action = "store_true",
        help = "should a 3rd person camera be rendered behind the ego vehicle",
    )
    run.add_argument(
        "--detailed-report",
        action = "store_true",
        help = "returns a more detailed report",
    )
    run.add_argument(
        "--filter-report",
        action = "store_true",
        help = "filters the report based on scene statuses",
    )
    run.add_argument(
        "--report-groups",
        nargs = "+",
        type = str.lower,
        default = [],
        action = "extend",
        choices = ["failed", "passed", "invalid"],
        help = "the scene statuses to filter the report on"
    )
    run.add_argument(
        "scenic_file",
        help = "a Scenic file to run",
        metavar = "FILE"
    )

    rerun = subparsers.add_parser(
        "rerun",
        parents = [common],
        help = "rerun a scenic scene",
        description = "rerun a scenic scene.",
    )
    rerun.add_argument(
        "--rtf",
        help = "maxium rtf to run the simulation at",
        type = float,
        default = None,
    )
    rerun.add_argument(
        "--scenes",
        nargs = "+",
        type = str.lower,
        default = [],
        action = "extend",
        metavar = "ID|START-END",
        help = "scene IDs or inclusive ranges to rerun (default: all)",
    )
    rerun.add_argument(
        "--render",
        action = "store_true",
        help = "should a 3rd person camera be rendered behind the ego vehicle",
    )
    rerun.add_argument(
        "--detailed-report",
        action = "store_true",
        help = "returns a more detailed report",
    )
    rerun.add_argument(
        "scene_dir",
        help = "a directory containg Scenes to run",
        metavar = "DIR"
    )
    
    return parser

def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> argparse.Namespace:
    if args.command == "run":

        if not os.path.isfile(args.scenic_file):
            parser.error("scenic_file requires a path to a existing file")

        if args.ego_car_config is not None and not os.path.isfile(args.ego_car_config):
            parser.error("--ego-car-config requires a path to a existing file")

        # Check if there are hard stop conditions that guarantee the program will eventually stop
        hard_stop_present = False
        for condition in ["count", "duration"]:
            if condition in args.stop_conditions:
                hard_stop_present = True
                break

        if not hard_stop_present:
            any_defined = False

            # If count is defined assume the user would want count to be enforced
            if args.count > 0:
                args.stop_conditions.append("count")
                any_defined = True
                logger.info("No hard stop-conditions provided and count is defined: adding 'count' as a stop condition")

            # If duration is defined assume the user would want duration to be enforced
            if args.duration > 0:
                args.stop_conditions.append("duration")
                any_defined = True
                logger.info("No hard stop-conditions provided and duration is defined: adding 'duration' as a stop condition")

            # If neither count nor duration is defined add duration as a default hard limit
            if any_defined == False:

                # If stop conditions is completely empty, also add first-failed as a stop condition 
                added_first_failed = ""
                if len(args.stop_conditions) == 0:
                    added_first_failed = " 'first-failed' and"
                    args.stop_conditions.append("first-failed")

                args.stop_conditions.append("duration")
                args.duration = 600

                logger.info(f"No hard stop-conditions provided: adding{added_first_failed} 'duration' as stop condition (the duration is set to 60 minutes)")

        if args.count > 0 and "count" not in args.stop_conditions:
            logger.warning("Count is defined but is not present in stop-conditions")

        if args.duration > 0 and "duration" not in args.stop_conditions:
            logger.warning("Duration is defined but is not present in stop-conditions")

        if "count" in args.stop_conditions and args.count <= 0:
            parser.error("--stop-conditions count requires --count N")

        if "duration" in args.stop_conditions and args.duration <= 0:
            parser.error("--stop-conditions duration requires --duration N")

        if args.filter_report == False and len(args.report_groups) != 0:
            logger.warning("Report-groups is defined but filter-report is false")

        if args.save_scenes == False and len(args.save_groups) != 0:
            logger.warning("Save-groups is defined but save-scenes is false")

        # If we want to filter the report but no filters are provided use the save groups if they exist or assume we want to filter to failed only
        if args.filter_report == True and len(args.report_groups) == 0:
            if len(args.save_groups) != 0 and args.save_scenes:
                args.report_groups = args.save_groups
                logger.info("No report groups provided and save groups is defined: using save groups as report groups")
            else:
                args.report_groups = ["failed"]

        # Warn and disable ros2 logging if saving scenes is false as there is no point wasting compute on recording
        if args.record_ros2 == True and args.save_scenes == False:
            args.record_ros2 = False
            logger.warning("Record-ros2 is true but save-scenes is false: disabling record-ros2")

        # Give save groups its default of failed
        if len(args.save_groups) == 0:
            args.save_groups = ["failed"]

    if args.command == "rerun":
        if not os.path.isdir(args.scene_dir):
            parser.error("scene_dir requires a path to a existing folder")

        with open(os.path.join(args.scene_dir, "metadata.json"), "r") as file:
            metadata = json.load(file)

        # By default simply run all scenes
        if len(args.scenes) == 0:
            args.scenes.append("all")
            logger.info("No scenes provided: running all saved scenes")

        run_scenes = []
        # Parse the requested scenes
        for item in args.scenes:
            item_scenes = [[], 1] # [scenes, # of repetitions]

            # Handle multipliers in requested scenes
            processed_item = item
            if "x" in item:
                multiplier_map = item.split("x")

                # Multipliers should be of the format {any}x{number}
                if len(multiplier_map) != 2:
                    parser.error(f"--scene has an invalid multiplier: {item}")
                if not multiplier_map[1].isdigit():
                    parser.error(f"--scene has an invalid multiplier: {item}")

                multiplier = int(multiplier_map[1])

                # Check that the multiplier number is valid
                if multiplier <= 0:
                    parser.error(f"--scene has an invalid multiplier: {item}")

                item_scenes[1] = multiplier

                # Remove the multiplier from the string to make it easier
                processed_item = multiplier_map[0]

            if processed_item == "all":
                # If the item is all simply add all saved scenes
                for scene in metadata["scenes"]:
                    if scene["scene_saved"] == True:
                        item_scenes[0].append(scene["scene"])
            elif "-" in processed_item:
                # If the item is a range get the min and max
                range_map = processed_item.split("-")

                # Ranges should be of the format {number}-{number}
                if len(range_map) != 2:
                    parser.error(f"--scene has an invalid range: {item}")

                if not range_map[0].isdigit():
                    parser.error(f"--scene has an invalid range: {item}")
                if not range_map[1].isdigit():
                    parser.error(f"--scene has an invalid range: {item}")

                range_start = int(range_map[0])
                range_end = int(range_map[1])

                # Validate ordering
                if range_start >= range_end:
                    parser.error(f"--scene has an invalid range: {item} (start must be less then end)")

                # Add scenes inclusive
                item_scenes[0] = list(range(range_start, range_end + 1))
            elif processed_item.isdigit():
                item_scenes[0] = [int(processed_item)]
            else:
                parser.error(f"--scene has an invalid item: {item}")

            run_scenes.append(item_scenes)

        # Get a simple list of which scenes were saved
        valid_scenes = [x["scene"] for x in metadata["scenes"] if x["scene_saved"] == True]

        # Combine all of the scene requests and their multipliers into a first seen ordered dict
        # Eg: [multiple scenes, # of repetitions] -> {unique scene: [unique scene, # of repetitions]}
        args.scenes = {}
        for scene in run_scenes:
            for item in scene[0]:
                # Check if the requested scene was actually saved
                if item in valid_scenes:
                    # Create or accumulate the multiplier 
                    if item in args.scenes:
                        args.scenes[item][1] += scene[1]
                    else:
                        args.scenes[item] = [item, scene[1]]
                else:
                    parser.error(f"--scene has an invalid id: {item}")

        # The dict was simply for ease of checking existance so convert the dict into a list by removing all its keys
        args.scenes = list(args.scenes.values())

    return args

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    args = parser.parse_args(argv)

    # Configure basic logging and scenic
    logging.basicConfig(
        level = getattr(logging, args.log_level),
        format = "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S"
    )
    scenic.setDebuggingOptions(
        verbosity = args.verbosity,
    )

    args = validate_args(parser, args)

    if args.command == "run":
        return run_command(args)
    elif args.command == "rerun":
        return rerun_command(args)

    return 2
