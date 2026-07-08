# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses

# requirements

- so far we've only testing a combo run with a single suite
- in the real world, we'll run multiple suites
- each suite needs a unique name
- for our maccity suite, the name should be "simple-maccity"
- include the suite name in descriptive statistics output