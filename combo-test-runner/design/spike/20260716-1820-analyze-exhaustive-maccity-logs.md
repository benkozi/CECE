- run this command:
```
uv run pytest src/tests/test_driver_combos.py \
  --suite-config=src/tests/config/suite/exhaustive-maccity-run-only-suite.yaml -vs
```
- analyze log output from the cece driver
- report any failures or abnormal output
  - include warnings as they may indiate problems in the driver
- enable suite "assertions". file count, etc.
- create a markdown report in combo-test-runner/design/spike_artifacts summarizing failures
- no code changes! if code changes are required, surface requirements and we'll make feature and revisit the spike
- goal: identify anything fishy in the cece execution. it says it works, but does it?
  - only looking at execution, no interest in the output contents at this pointK