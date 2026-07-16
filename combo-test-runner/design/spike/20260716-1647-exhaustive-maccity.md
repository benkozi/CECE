# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses
  - all pydantic fields should include a description like `... = Field(description="<description content here>", ...`
- do *not* add driver bugs to known bugs in `README.md` unless explicitly told to do so
- use a test-driven development, red-green-refactor approach for all fixes and features (when possible)
- maintain original `always do` and `requirements` sections when refining design docs

# requirements

- create an exhaustive test suite based on simple-maccity-suite
- first, revisit the cece code to look for enums we are missing at the python level
  - remember the python enums are not connected to the c++ implementation
  - you may have to dig into extern code - take your time
- after updating the python enums, create the exhaustive test suite
- turn off all plotting, baselines, and statistics
  - this is a *run-only* test suite - we just want to know if the combinations passes or fails
- call the suite "exhaustive-maccity-run-only-suite.yaml"
- in fact, let's add a way to indicate all enum values should be tested. maybe a regex filter for the enums? `.*` would indicate all enums
  - the goal is to make this exhaustive suite always applicable. we don't want to update it every time we add a new enum
- there may be enum values that are not applicable and the driver will fail but that's okay. they can fail. think of this as spike in some ways
- we're going to need a "report" summarizing the results of the exhaustive test suite
  - this should be a csv with the pytest name, the combo_id, the combo name, and the result (pass/fail)