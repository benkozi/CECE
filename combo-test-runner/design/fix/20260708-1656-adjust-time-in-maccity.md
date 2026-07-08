# always do

- as part of plan, always include updating design.md as part of the implementation
- as part of plan, always update combo-test-runner tests in addition to any changes to test_driver_combos.py
- always use pydantic models as opposed to dataclasses

# requirements

- i changed the maccity config to run for 3 hours instead of 1 hour
- a number of combo test runner tests failed. update the tests to account for the change.
  - to simplify, extract number of expected timesteps to a test constant or fixture to only change in one place. keep it as a defined variable to ensure we test the timestep count calculator
