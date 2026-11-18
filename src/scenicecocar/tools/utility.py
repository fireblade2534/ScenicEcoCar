import scenic
import logging
from enum import Enum
import scenic.core
import scenic.core.scenarios
import scenic.core.simulators
import scenic.core.errors as errors

logger = logging.getLogger(__name__)

class SimulationResultType(Enum):
    PASSED = 1
    FAILED = 2
    INVALID = 3

def run_simulation(
        simulator: scenic.core.simulators.Simulator,
        scene: scenic.core.scenarios.Scene,
        max_steps: int | None = None,
        name: str = "simulation",
        verbosity: int = 0,
        max_iterations: int = 1
    ) -> SimulationResultType:

    try:
        simulation = errors.callBeginningScenicTrace(
            lambda: simulator.simulate(
                scene,
                maxSteps = max_steps,
                name = str(name),
                verbosity = verbosity,
                maxIterations = max_iterations,
            )
        )
    except scenic.core.simulators.SimulationCreationError as E:
        logging.error(f"Failed to create simulation: {E}")

        return SimulationResultType.INVALID

    return check_pass(simulation)
    

def check_pass(simulation: scenic.core.simulators.Simulation) -> SimulationResultType:
    passed = simulation.result.records["PASSED"]

    if type(passed) is not bool:
        raise RuntimeError(
            f"record `PASSED` contains {passed!r} ({type(passed).__name__}), expected bool"
        )

    if passed == False:
        return SimulationResultType.FAILED

    failed = simulation.result.records.get("FAILED", None)
    if failed is not None:
        if type(failed) is bool:
            if failed == True:
                return SimulationResultType.FAILED
        elif isinstance(failed, list):
            for step, value in failed:
                if type(value) is not bool:
                    raise RuntimeError(
                        f"record `FAILED` at step {step}, contains {value!r} ({type(value).__name__}), expected bool"
                    )

                if value == True:
                    return SimulationResultType.FAILED

        else:
            raise RuntimeError(
                f"record `FAILED` contains {failed!r} ({type(failed).__name__}), expected bool"
            )

    return SimulationResultType.PASSED