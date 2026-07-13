# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses
- do *not* add driver bugs to known bugs in `README.md` unless explicitly told to do so

# requirements

- fix the driver bug mentioned in combo-test-runner/design/feat/20260713-1049-expected-output-units.md
- the fix likely involves some communication between extern/helm/libs/conf and extern/helm/libs/amio
- look into how best to add a script to build CECE and run the test suite in the container in setup.sh