from types import FunctionType

def repair_condition(condition):
    atoms = tuple(condition.atomics())
    if not atoms:
        return
    
    namespace = atoms[0].closure.__globals__

    for atom in atoms[1:]:
        function = atom.closure

        if function.__globals__ is namespace:
            continue

        rebuilt = FunctionType(
            function.__code__,
            namespace,
            function.__name__,
            function.__defaults__,
            function.__closure__,
        )

        rebuilt.__kwdefaults__ = function.__kwdefaults__
        rebuilt.__annotations__ = function.__annotations__
        rebuilt.__dict__.update(function.__dict__)
        rebuilt.__qualname__ = function.__qualname__
        rebuilt.__module__ = function.__module__
        rebuilt.__doc__ = function.__doc__

        atom.closure = rebuilt


def repair_scenario_globals(scenario):
    seen = set()

    for attribute in (
        "requirements",
        "monitors",
        "terminationConditions",
        "terminateSimulationConditions",
        "recordedExprs",
        "recordedInitialExprs",
        "recordedFinalExprs",
    ):
        for requirement in getattr(scenario, attribute, ()):
            condition = requirement.proposition

            if id(condition) not in seen:
                repair_condition(condition)
                seen.add(id(condition))