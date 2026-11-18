import scenic
import logging
from enum import Enum
import scenic.core
import scenic.core.simulators

logger = logging.getLogger(__name__)

class SimulationResultType(Enum):
    PASSED = 1
    FAILED = 2

def checkPass(simulation: scenic.core.simulators.Simulation) -> SimulationResultType:
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