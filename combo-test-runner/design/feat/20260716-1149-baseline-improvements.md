# always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses
  - all pydantic fields should include a description like `... = Field(description="<description content here>", ...`
- do *not* add driver bugs to known bugs in `README.md` unless explicitly told to do so
- use a test-driven development, red-green-refactor approach for all fixes and features (when possible)

# requirements

- generate additional statistical output for the comparison
  - rmse
  - descriptive stats summarizing the difference --> min difference/max difference/etc
- generate bias plots for each file and a gif
  - plots gifs always created
- summarize in a stats-comparison.csv file per combination and also at the root output level
- probably best to convert the -comparison.yaml to a csv file and just concatenate those
- rename "plots" folder to "plots-overview"
- new "plots-baselines" folder for bias plots and gifs
- add a configuration option to the baselines_comparison to turn plotting on/off