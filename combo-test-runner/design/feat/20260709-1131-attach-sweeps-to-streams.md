# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses

# requirements

- sweeps need to be attached to streams or other potential configuration groups
- for example, `mapalgo` is nested:
```
cece_data:
  streams:
  - name: MACCITY
    file: /work/data/MACCity_4x5.nc
    yearFirst: 2000
    yearLast: 2010
    yearAlign: 2020
    taxmode: cycle
    tintalgo: linear
    mapalgo: consd
    variables:
    - file: MACCity
      model: co
```
- maybe sweep should mirror the config structure a bit more tightly:
```
sweep:
  cece_data:
    streams:
      - name: MACCITY
      - mapalgo: [bilinear, consd, passthrough]
```