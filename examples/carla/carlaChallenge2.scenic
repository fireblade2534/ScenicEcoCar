
""" Scenario Description
Traffic Scenario 02.
Longitudinal control after leading vehicle's brake.

The leading vehicle decelerates suddenly due to an obstacle.
The ego vehicle must perform an emergency brake or avoidance
maneuver.

To run:
    scenic examples/carla/Judged_Carla/carlaChallenge2.scenic \
        --simulate --count 10 --report-results
"""

## MAP AND MODEL

param map = localPath('../../assets/maps/carla/Town01.xodr')
param carla_map = 'Town01'
model scenic.simulators.carla.model


## CONSTANTS

EGO_MODEL = "vehicle.lincoln.mkz_2017"

LEAD_CAR_SPEED = 10
LEADCAR_BRAKING_THRESHOLD = 10

BRAKE_ACTION = 1.0


## BEHAVIORS
behavior LeadingCarBehavior(speed=10):
    try:
        do FollowLaneBehavior(speed)

    interrupt when withinDistanceToAnyObjs(self, LEADCAR_BRAKING_THRESHOLD):
        take SetBrakeAction(BRAKE_ACTION)


## SCENARIO GENERATION

lane = Uniform(*network.lanes)

obstacle = new Trash on lane.centerline

leadCar = new Car following roadDirection from obstacle for Range(-50, -30),
        with behavior LeadingCarBehavior(LEAD_CAR_SPEED)

ego = new Car following roadDirection from leadCar for Range(-15, -10),
        with blueprint EGO_MODEL


## SCENARIO VALIDITY

require (distance to intersection) > 80

require abs(relative heading of
    (roadDirection at ego.position)
    from (roadDirection at obstacle.position)) < 5 deg


## TEST TERMINATION

# Terminate when the ego safely stops near the obstacle.
terminate when (
    ego.speed < 0.1
    and (distance to obstacle) < 30
)

# Terminate if the ego collides with the lead car or obstacle.
terminate when (
    (ego intersects leadCar)
    or (ego intersects obstacle)
)

# Maximum simulation duration.
terminate after 300 steps


## TEST EVALUATION

# REQUIRED: The ego must achieve its stopping objective.
record final (
    ego.speed < 0.1
    and (distance to obstacle) < 30
) as PASSED

# OPTIONAL: Any collision during the simulation fails the test.
# This is checked at every simulation step.
record bool(ego intersects leadCar) as FAILED_LEADCAR_INTERSECT
record bool(ego intersects obstacle) as FAILED_OBSTACLE_INTERSECT
