from __future__ import annotations

import re
from enum import StrEnum, unique
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from models.base import StrictModel

# ── YAML loader that follows YAML 1.2 boolean rules (true/false only) ────────
# PyYAML (YAML 1.1) also maps yes/no/on/off to booleans, which collides with
# species names like "no". Strip the inherited bool resolver from SafeLoader
# and replace it with one that only accepts true/false.

_BOOL_TAG = "tag:yaml.org,2002:bool"
_BOOL_RE = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class _StrictBoolLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


# Build a fresh copy of the parent's resolver map with the bool tag removed,
# then add back a YAML-1.2-compatible resolver (true/false only).
_StrictBoolLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictBoolLoader.add_implicit_resolver(_BOOL_TAG, _BOOL_RE, list("tTfF"))  # type: ignore


# ── Enums ────────────────────────────────────────────────────────────────────


@unique
class Operation(StrEnum):
    add = "add"  # type: ignore[assignment]  # StrEnum.__new__ typing limitation
    replace = "replace"  # type: ignore[assignment]


@unique
class Taxmode(StrEnum):
    cycle = "cycle"
    extend = "extend"


@unique
class Tintalgo(StrEnum):
    linear = "linear"
    nearest = "nearest"


@unique
class Mapalgo(StrEnum):
    consd = "consd"
    bilinear = "bilinear"
    passthrough = "passthrough"
    consf = "consf"
    nn = "nn"
    redist = "redist"


@unique
class Category(StrEnum):
    anthropogenic = "anthropogenic"
    biomass_burning = "biomass_burning"
    transportation = "transportation"
    energy = "energy"
    natural = "natural"
    biogenic = "biogenic"


@unique
class VdistMethod(StrEnum):
    pbl = "PBL"
    height = "HEIGHT"
    pressure = "PRESSURE"


# ── Sub-models ────────────────────────────────────────────────────────────────


class Grid(StrictModel):
    nx: int = Field(description="Number of longitude grid cells")
    ny: int = Field(description="Number of latitude grid cells")
    lon_min: float = Field(description="Western boundary of the domain (degrees east)")
    lon_max: float = Field(description="Eastern boundary of the domain (degrees east)")
    lat_min: float = Field(description="Southern boundary of the domain (degrees north)")
    lat_max: float = Field(description="Northern boundary of the domain (degrees north)")


class Driver(StrictModel):
    start_time: str = Field(description="Simulation start time (ISO-8601)")
    end_time: str = Field(description="Simulation end time (ISO-8601)")
    timestep_seconds: int = Field(description="Model timestep in seconds")
    grid: Grid = Field(description="Spatial grid definition")


class SpeciesEntry(StrictModel):
    field: str = Field(description="Name of the source field in the export state")
    operation: Operation = Field(description="How this entry combines with prior entries for the same species")
    scale: float | None = Field(None, description="Multiplicative scale factor applied to the field")
    category: Category | None = Field(None, description="Emission source category")
    hierarchy: int | None = Field(
        None,
        description="Priority level; higher values override lower when operation is 'replace'",
    )
    mask: str | None = Field(
        None,
        description="Name of the mask field (defined in meteorology) limiting where this entry applies",
    )
    diurnal_cycle: str | None = Field(
        None,
        description="Key into temporal_profiles for an hourly (24-element) scaling profile",
    )
    weekly_cycle: str | None = Field(
        None,
        description="Key into temporal_profiles for a day-of-week (7-element) scaling profile",
    )
    seasonal_cycle: str | None = Field(
        None,
        description="Key into temporal_profiles for a monthly (12-element) scaling profile",
    )
    scale_fields: list[str] | None = Field(
        None,
        description="Export-state fields used as additional multiplicative scaling (e.g. temperature, LAI)",
    )
    vdist_method: VdistMethod | None = Field(None, description="Vertical distribution method")
    vdist_h_start: float | None = Field(
        None,
        description="Lower bound of vertical injection layer (metres); used with HEIGHT method",
    )
    vdist_h_end: float | None = Field(
        None,
        description="Upper bound of vertical injection layer (metres); used with HEIGHT method",
    )
    vdist_p_start: float | None = Field(
        None,
        description="Lower bound of vertical injection layer (Pa); used with PRESSURE method",
    )
    vdist_p_end: float | None = Field(
        None,
        description="Upper bound of vertical injection layer (Pa); used with PRESSURE method",
    )


class StreamVariable(StrictModel):
    file: str = Field(description="Variable name in the source NetCDF file")
    model: str = Field(description="Corresponding field name in the export state")


class Stream(StrictModel):
    name: str = Field(description="Unique identifier for this data stream")
    file: Path = Field(description="Path to the source NetCDF file (glob patterns supported)")
    yearFirst: int = Field(description="First year of data available in the file")
    yearLast: int = Field(description="Last year of data available in the file")
    yearAlign: int = Field(description="Simulation year to align the data to when cycling or extending")
    taxmode: Taxmode = Field(description="Behaviour when the simulation time falls outside [yearFirst, yearLast]")
    tintalgo: Tintalgo = Field(description="Temporal interpolation algorithm")
    mapalgo: Mapalgo = Field(description="Horizontal regridding algorithm")
    refresh_interval_seconds: int | None = Field(
        None,
        description="How often to re-read the file during a run; None means read once at start",
    )
    variables: list[StreamVariable] = Field(description="Mapping from file variable names to export-state field names")


class CeceData(StrictModel):
    streams: list[Stream] = Field(description="Ordered list of external data streams ingested by the stacking engine")


class PhysicsScheme(StrictModel):
    name: str = Field(description="Registered name of the physics scheme")
    language: str | None = Field(
        None,
        description="Implementation language (e.g. 'cpp'); defaults to the engine's native language",
    )
    refresh_interval_seconds: int | None = Field(
        None,
        description="How often the scheme is re-evaluated during a timestep; None means once per timestep",
    )
    options: dict[str, Any] | None = Field(None, description="Scheme-specific configuration options")
    input_mapping: dict[str, str] | None = Field(
        None,
        description="Maps scheme input parameter names to export-state field names",
    )
    output_mapping: dict[str, str] | None = Field(
        None,
        description="Maps scheme output parameter names to export-state field names",
    )


class Diagnostics(StrictModel):
    output_interval_seconds: int = Field(description="How frequently diagnostic output is written, in seconds")
    variables: list[str] = Field(default=[], description="Export-state fields to include in diagnostic output")
    enabled: bool | None = Field(
        None,
        description="Whether diagnostic output is active; defaults to True when this section is present",
    )


class Output(StrictModel):
    enabled: bool = Field(description="Whether NetCDF output is written")
    directory: str = Field(description="Directory where output files are written")
    filename_pattern: str = Field(description="Filename template; supports {YYYY}, {MM}, {DD}, {HH}, {mm}, {ss} tokens")
    frequency_steps: int = Field(description="Number of timesteps between output writes")
    fields: list[str] = Field(description="Export-state fields written to each output file")


# ── Top-level ─────────────────────────────────────────────────────────────────


class CeceConfig(StrictModel):
    driver: Driver = Field(description="Simulation time and spatial grid settings")
    meteorology: dict[str, str] | None = Field(
        None,
        description="Maps logical meteorology variable names to export-state field names",
    )
    scale_factors: dict[str, str] | None = Field(
        None, description="Maps logical scale-factor names to export-state field names"
    )
    masks: dict[str, str] | None = Field(None, description="Maps logical mask names to export-state field names")
    temporal_profiles: dict[str, list[float]] | None = Field(
        None,
        description="Named temporal scaling profiles (diurnal, weekly, seasonal) referenced by species entries",
    )
    species: dict[str, list[SpeciesEntry]] = Field(
        description="Per-species stacking instructions; keys are species names (e.g. 'co', 'nox')"
    )
    physics_schemes: list[PhysicsScheme] | None = Field(
        None, description="Physics schemes executed each timestep, in order"
    )
    cece_data: CeceData = Field(description="External data streams ingested by the stacking engine")
    diagnostics: Diagnostics | None = Field(None, description="Diagnostic output configuration")
    output: Output | None = Field(None, description="NetCDF output configuration")

    @classmethod
    def from_yaml(cls, path: Path) -> CeceConfig:
        with open(path) as f:
            return cls.model_validate(yaml.load(f, Loader=_StrictBoolLoader))

    def to_yaml(self, path: Path) -> None:
        with open(path, "w") as f:
            yaml.dump(
                self.model_dump(exclude_none=True, mode="json"),
                f,
                default_flow_style=False,
                sort_keys=False,
            )
