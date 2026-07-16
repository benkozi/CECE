# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses
  - all pydantic fields should include a description like `... = Field(description="<description content here>", ...`
- do *not* add driver bugs to known bugs in `README.md` unless explicitly told to do so
- use a test-driven development, red-green-refactor approach for all fixes and features (when possible)

# requirements

- netcdf output from combination runs need to be optionally compared with a baseline
- a realization<->baseline pair occurs at the *combination* level. we may not have baselines for all combinations
  - check all netcdf outputs from a combination
  - the file count and names must match exactly
  - a baseline is found using a ULID identifier
- comparison should model nccmp. it needs to check data bit-for-bit or with a tolerance, global attributes, and field attributes.
  - bit-for-bit is default (rtol=0), if rtol is a float great than zero, then use a tolerance. tolerance should be 0 or positive float
  - right now always check attributes (global and variable level). assume exact
  - variable counts and names match exactly
  - dimension sizes and names match exactly
  - netcdf file type matches exactly
- eventually, baselines will be retrieved online, but now assume they are stored locally
  - add a setting: `baseline_root_dir` (default: `None`). if none, assume cwd
  - so, expect a baseline at <base_line_root_dir>/<ulid>
  - in future work, we will create baselines that will have a manifest linking ULIDs to a combination and other metadata
- use parallel xarray to speed comparison
- following the comparison, generate a yaml file describing the comparison results
  - have the comparison generate a pydantic model that is converted to yaml