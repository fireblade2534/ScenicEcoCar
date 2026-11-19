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
        "--scenes",
        nargs = "+",
        type = str.lower,
        default = [],
        action = "extend",
        metavar = "ID|START-END",
        help = "scene IDs or inclusive ranges to rerun (default: all)",
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

        hard_stop_present = False
        for condition in ["count", "duration"]:
            if condition in args.stop_conditions:
                hard_stop_present = True
                break

        if not hard_stop_present:
            any_defined = False

            if args.count > 0:
                args.stop_conditions.append("count")
                any_defined = True
                logger.info("No hard stop-conditions provided and count is defined: adding 'count' as a stop condition")

            if args.duration > 0:
                args.stop_conditions.append("duration")
                any_defined = True
                logger.info("No hard stop-conditions provided and duration is defined: adding 'duration' as a stop condition")

            if any_defined == False:

                added_first_failed = ""
                if len(args.stop_conditions) == 0:
                    added_first_failed = " 'first-failed' and"
                    args.stop_conditions.append("first-failed")

                args.stop_conditions.append("duration")
                args.duration = 3600

                logger.info(f"No hard stop-conditions provided: adding{added_first_failed} 'duration' as stop condition (the duration is set to 60 minutes)")

        if args.count > 0 and "count" not in args.stop_conditions:
            logger.warning("Count is defined but is not present in stop-conditions")

        if args.duration > 0 and "duration" not in args.stop_conditions:
            logger.warning("Duration is defined but is not present in stop-conditions")

        if "count" in args.stop_conditions and args.count <= 0:
            parser.error("--stop-conditions count requires --count N")

        if "duration" in args.stop_conditions and args.duration <= 0:
            parser.error("--stop-conditions duration requires --duration N")

        if len(args.save_groups) == 0:
            args.save_groups = ["failed"]

    if args.command == "rerun":
        if not os.path.isdir(args.scene_dir):
            parser.error("scene_dir requires a path to a existing folder")

        with open(os.path.join(args.scene_dir, "metadata.json"), "r") as file:
            metadata = json.load(file)

        
        if len(args.scenes) == 0:
            args.scenes.append("all")
            logger.info("No scenes provided: running all saved scenes")

        run_scenes = []
        if "all" in args.scenes:
            for scene in metadata["scenes"]:
                run_scenes.append(scene["scene"])
        else:
            for item in args.scenes:
                if "-" in item:
                    range_map = item.split("-")

                    if len(range_map) != 2:
                        parser.error(f"--scene has an invalid range: {item}")

                    if not range_map[0].isdigit():
                        parser.error(f"--scene has an invalid range: {item}")
                    if not range_map[1].isdigit():
                        parser.error(f"--scene has an invalid range: {item}")

                    range_start = int(range_map[0])
                    range_end = int(range_map[1])

                    if range_start >= range_end:
                        parser.error(f"--scene has an invalid range: {item} (start must be less then end)")

                    run_scenes.extend(
                        range(range_start, range_end + 1)
                    )

                elif item.isdigit():
                    run_scenes.append(int(item))
                else:
                    parser.error(f"--scene has an invalid item: {item}")

        run_scenes.sort()
        run_scenes = list(dict.fromkeys(run_scenes))

        valid_scenes = [x["scene"] for x in metadata["scenes"] if x["scene_saved"] == True]

        args.scenes = []
        for scene in run_scenes:
            if scene in valid_scenes:
                args.scenes.append(scene)
            else:
                parser.error(f"--scene has an invalid id: {scene}")
                
    return args

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    args = parser.parse_args(argv)

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

    if args.command == "rerun":
        return rerun_command(args)

    return 2
