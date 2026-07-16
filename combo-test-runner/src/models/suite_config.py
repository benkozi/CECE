from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ConfigDict, Field, field_validator, model_validator

from models.base import StrictModel
from models.cece_config import (
    Category,
    Mapalgo,
    Operation,
    Taxmode,
    Tintalgo,
    VdistMethod,
)


# General string-assertion sentinel: "don't check". A plain null cannot serve
# because null already means "assert the value is absent".
IGNORE_VALUE = "__ignore__"


def _unique_values(values: list | None) -> list | None:
    """Duplicate sweep values would enumerate two combinations with the same
    id and directory — rejected loudly rather than deduped."""
    if values is not None and len(values) != len(set(values)):
        raise ValueError("duplicate values in sweep list")
    return values


class StreamSweep(StrictModel):
    """Swept dimensions attached to one stream, selected by name."""

    name: str = Field(description="Stream in the base config this sweep attaches to")
    taxmode: list[Taxmode] | None = Field(None, min_length=1)
    tintalgo: list[Tintalgo] | None = Field(None, min_length=1)
    mapalgo: list[Mapalgo] | None = Field(None, min_length=1)

    _unique = field_validator("taxmode", "tintalgo", "mapalgo")(_unique_values)


class CeceDataSweep(StrictModel):
    streams: list[StreamSweep] = Field(min_length=1)

    @field_validator("streams")
    @classmethod
    def _unique_stream_names(cls, streams: list[StreamSweep]) -> list[StreamSweep]:
        names = [stream.name for stream in streams]
        if len(names) != len(set(names)):
            raise ValueError("duplicate stream names in sweep")
        return streams


class SpeciesEntrySweep(StrictModel):
    """Swept dimensions attached to one species entry, selected by list
    position (sweep list index i -> species.<name>[i]); {} skips an entry."""

    operation: list[Operation] | None = Field(None, min_length=1)
    category: list[Category] | None = Field(None, min_length=1)
    vdist_method: list[VdistMethod] | None = Field(None, min_length=1)

    _unique = field_validator("operation", "category", "vdist_method")(_unique_values)


class Sweep(StrictModel):
    """Sweeps mirror the driver-config structure and attach to named streams
    or positional species entries. The combination space is the cartesian
    product of every attached value list."""

    cece_data: CeceDataSweep | None = None
    species: dict[str, list[SpeciesEntrySweep]] | None = None


class AttributesAssertion(StrictModel):
    """Expected attribute dictionary for a species' variable. Per-value
    semantics: a string asserts exact equality, null asserts absence, and
    IGNORE_VALUE ("__ignore__") places no constraint on the value."""

    exact: bool = Field(
        True,
        description="True: attribute dictionaries match exactly (unmentioned found attributes fail); False: expected is a subset",
    )
    expected: dict[str, str | None] = Field(
        default_factory=dict,
        description="Attribute name -> expected value (string), null (must be absent), or '__ignore__' (any value)",
    )


class SpeciesAssertions(StrictModel):
    """Per-species expectations about the NetCDF output."""

    attributes: AttributesAssertion | None = Field(
        None,
        description="Full attribute-dictionary expectation for the species' variable; None = no attribute test",
    )


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
    species: dict[str, SpeciesAssertions] | None = Field(
        None,
        description="Per-species output expectations, keyed by species name; absent species are not checked",
    )


class Analysis(StrictModel):
    """Post-run analysis steps. Like Assertions, configures what to compute,
    never run behavior."""

    compute_descriptive_stats: bool = Field(
        True,
        description="Compute per-NetCDF descriptive statistics and write per-combo + suite-level CSVs; false skips",
    )


class Plotting(StrictModel):
    """Spatial-plot rendering at session end. The shared color scale derives
    from the descriptive statistics, so plotting requires the stats step."""

    enabled: bool = Field(
        True, description="Render spatial plots per NetCDF into <combo>/plots/"
    )
    gif_enabled: bool = Field(
        True, description="Assemble the per-variable plots into an animated GIF"
    )


class SuiteConfig(StrictModel):
    name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description=(
            "Unique suite name (lowercase slug); by convention suite 'X' lives in X-suite.yaml, "
            "but this field is authoritative"
        ),
    )
    config_path: Path = Field(
        description="Base CECE driver config this suite's combinations are diffs of"
    )
    analysis: Analysis = Field(
        default_factory=Analysis,
        description="Post-run analysis configuration; defaults apply when absent",
    )
    plotting: Plotting = Field(
        default_factory=Plotting,
        description="Session-end spatial plotting; defaults apply when absent",
    )

    @model_validator(mode="after")
    def _plotting_requires_stats(self) -> SuiteConfig:
        if self.plotting.enabled and not self.analysis.compute_descriptive_stats:
            raise ValueError(
                "plotting.enabled requires analysis.compute_descriptive_stats: the shared "
                "color scale derives from the descriptive statistics (disable plotting to "
                "run stats-less)"
            )
        return self

    assertions: Assertions = Field(
        default_factory=Assertions,
        description="Post-run assertion expectations; defaults apply when absent",
    )
    timeout_s: int = Field(
        gt=0,
        description="Per-combination driver timeout in seconds; capped by the run_timeout_s setting",
    )
    sweep: Sweep = Field(
        description="Enum dimensions and values defining the combination space"
    )

    @classmethod
    def from_yaml(
        cls, path: Path, config_search_path: Path | None = None
    ) -> SuiteConfig:
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
            yaml.dump(
                self.model_dump(mode="json"),
                f,
                default_flow_style=False,
                sort_keys=False,
            )
