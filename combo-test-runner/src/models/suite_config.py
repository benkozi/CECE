from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ConfigDict, Field

from models.base import StrictModel
from models.cece_config import Category, Mapalgo, Operation, Taxmode, Tintalgo, VdistMethod


class Sweep(StrictModel):
    """Enum values to sweep. Enums left unset are not swept and stay at their
    base-config values; the combination space is the cartesian product of the
    listed values."""

    operation: list[Operation] | None = Field(None, min_length=1)
    category: list[Category] | None = Field(None, min_length=1)
    vdist_method: list[VdistMethod] | None = Field(None, min_length=1)
    taxmode: list[Taxmode] | None = Field(None, min_length=1)
    tintalgo: list[Tintalgo] | None = Field(None, min_length=1)
    mapalgo: list[Mapalgo] | None = Field(None, min_length=1)


class Assertions(StrictModel):
    """What each combination's output is expected to look like. Configures
    expectations only — never run behavior (fail-fast stays pytest's -x)."""

    expected_nc_file_count: int | None = Field(
        None,
        ge=0,
        description="Exact NetCDF file count per combo; None derives it from the combo config; 0 means none expected",
    )
    validate_filenames: bool = Field(
        True,
        description="Assert NetCDF filenames match filename_pattern at the expected write times; false skips the test",
    )


class Analysis(StrictModel):
    """Post-run analysis steps. Like Assertions, configures what to compute,
    never run behavior."""

    compute_descriptive_stats: bool = Field(
        True,
        description="Compute per-NetCDF descriptive statistics and write per-combo + suite-level CSVs; false skips",
    )


class SuiteConfig(StrictModel):
    config_path: Path = Field(description="Base CECE driver config this suite's combinations are diffs of")
    analysis: Analysis = Field(
        default_factory=Analysis,
        description="Post-run analysis configuration; defaults apply when absent",
    )
    assertions: Assertions = Field(
        default_factory=Assertions,
        description="Post-run assertion expectations; defaults apply when absent",
    )
    timeout_s: int = Field(
        gt=0,
        description="Per-combination driver timeout in seconds; capped by the run_timeout_s setting",
    )
    sweep: Sweep = Field(description="Enum dimensions and values defining the combination space")

    @classmethod
    def from_yaml(cls, path: Path, config_search_path: Path | None = None) -> SuiteConfig:
        """Load a suite file; config_path is resolved to an absolute host path.

        Relative config_path values resolve against the suite file's own
        directory, or against config_search_path when set (prepended verbatim,
        so nested and ../ paths work). Absolute values are used as-is. A
        missing target fails here, before any containers run.
        """
        with open(path) as f:
            suite = cls.model_validate(yaml.safe_load(f))
        if suite.config_path.is_absolute():
            resolved = suite.config_path
        elif config_search_path is not None:
            resolved = config_search_path / suite.config_path
        else:
            resolved = path.parent / suite.config_path
        resolved = resolved.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(
                f"suite config_path {str(suite.config_path)!r} resolved to {resolved}, which does not exist"
            )
        suite.config_path = resolved
        return suite


class RunManifest(StrictModel):
    """Output-only record of one test run, written to the output root as
    run.yaml. The run_id is generated at runtime (never read from
    configuration); the suite is recorded as resolved — what actually ran."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str  # session ULID; its timestamp encodes the run start
    suite: SuiteConfig

    def to_yaml(self, path: Path) -> None:
        with open(path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
