# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses

# requirements

- add an assertion for `species.co`
- there might be a number of assertions eventually across different species
- initially this assertion is to verify the output units of the field in the nc file
- so the assertions section could look like:
```
assertions:
  species:
    co:
      units: null/<expected units>
```
- if the units are `null` then expect no units. if the value is "__ignore__" then don't check units. assume this is the default.
  - add an item to the design.md indicating this value should be used to ignore string values when testing assertions
- there is a bug in the driver and the test is not expected to pass
  - the unis are coming out as mol-1 mol or something which is not correct