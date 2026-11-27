import scenic
import logging
from enum import Enum
import scenic.core
from scenic.core.dynamics.guards import InvariantViolation
import scenic.core.scenarios
import scenic.core.simulators
import scenic.core.errors as errors
from datetime import timedelta
from scenic.core.errors import InvalidScenarioError

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
        max_iterations: int = 1,
        rtf: float | None = None,
    ) -> tuple[SimulationResultType, list[str], list[str]]:

    try:
        simulation = errors.callBeginningScenicTrace(
            lambda: simulator.simulate(
                scene,
                maxSteps = max_steps,
                name = str(name),
                verbosity = verbosity,
                maxIterations = max_iterations,
                raiseGuardViolations = True,
                rtf = rtf,
            )
        )
    except scenic.core.simulators.SimulationCreationError as E:
        logging.error(f"Failed to create simulation: {E}")
        return (SimulationResultType.INVALID, [], [])
    except InvariantViolation as e:
        logging.warning(f"Invariant violated: {e}")
        return (SimulationResultType.INVALID, [], [])

    if simulation is None:
        return (SimulationResultType.INVALID, [], [])

    return check_pass(simulation)
    
def is_failed_type(name: str) -> bool:
    if name.startswith("FAILED"):
        return True
    return False

def is_passed_type(name: str) -> bool:
    if name.startswith("PASSED"):
        return True
    return False

def validateTestRecords(scenerio: scenic.core.scenarios.Scenario) -> bool:
    failed_seen = set()
    passed_seen = set()

    # Both of the records are allowed to be finals
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

    # The failed records are allowed to be lists while the passed record can only be a final
    for record in scenerio.recordedExprs:
        if is_passed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record can only be a record final")

        if is_failed_type(record.name) == True:
            if record.name in failed_seen:
                raise InvalidScenarioError(f"Only one `{record.name}` record is allowed")
            failed_seen.add(record.name)

    # Neither of the records is allowed to be an inital
    for record in scenerio.recordedInitialExprs:
        if is_passed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record can only be a record final")

        if is_failed_type(record.name) == True:
            raise InvalidScenarioError(f"The `{record.name}` record cannot be a record initial")
        
    return True

def check_pass(simulation: scenic.core.simulators.Simulation) -> tuple[SimulationResultType, list[str], list[str]]:
    passed = []
    failed = []

    for key, record in simulation.result.records.items():
        if is_passed_type(key) == True:
            # For passed only single bools are allowed
            if type(record) is not bool:
                raise RuntimeError(
                    f"record `{key}` contains {record!r} ({type(record).__name__}), expected bool"
                )

            if record == True:
                passed.append(key)

        elif is_failed_type(key) == True:
            # For failed either a single bool or a list of booleans is allowed
            if type(record) is bool:
                if record == True:
                    failed.append(key)
            elif isinstance(record, list):
                for step, value in record:
                    if type(value) is not bool:
                        raise RuntimeError(
                            f"record `{key}` at step {step}, contains {value!r} ({type(value).__name__}), expected bool"
                        )

                    if value == True:
                        failed.append(key)
                        break

            else:
                raise RuntimeError(
                    f"record `{key}` contains {record!r} ({type(record).__name__}), expected bool"
                )

    # If any failed records are true the sim fails regardless of if there are any passed records
    if len(passed) == 0 or len(failed) > 0:
        return (SimulationResultType.FAILED, passed, failed)
    
    return (SimulationResultType.PASSED, passed, failed)

def format_time(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if sec or not parts:
        parts.append(f"{sec}s")
        
    return " ".join(parts)
