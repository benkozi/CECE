"""Sweep -> combinations: enumeration, naming, ids, and driver-config generation.

Dimensions are derived from the sweep and attached to named streams or
positional species entries. The sweep is normalized before enumeration
(targets and value lists sorted) so declaration order never influences combo
ids, names, or enumeration order.

All generated configs are built as CeceConfig instances and written only via
CeceConfig.to_yaml() so every config the driver receives has passed pydantic
validation.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

import pandas as pd

from logs import get_logger
from models.cece_config import CeceConfig, VdistMethod
from models.suite_config import Sweep

logger = get_logger("combos")

NAME_SEPARATOR = "__"  # shell-safe; nothing parses the name back (combos.csv does)

# Companion vdist bounds required for a valid config when sweeping VdistMethod.
_VDIST_HEIGHT_BOUNDS_M = (0.0, 100.0)
_VDIST_PRESSURE_BOUNDS_PA = (100000.0, 90000.0)

# Fixed canonical field order within a target: (config field, name tag).
_SPECIES_FIELDS: tuple[tuple[str, str], ...] = (
    ("operation", "op"),
    ("category", "cat"),
    ("vdist_method", "vd"),
)
_STREAM_FIELDS: tuple[tuple[str, str], ...] = (
    ("taxmode", "tax"),
    ("tintalgo", "tint"),
    ("mapalgo", "map"),
)


@dataclass(frozen=True)
class Dimension:
    target: str  # attachment target label, e.g. "MACCITY", "co", "co-1"
    field: str  # config field name, e.g. "mapalgo"
    tag: str  # short tag used in combination names, e.g. "map"
    apply: Callable[[CeceConfig, StrEnum], None]


@dataclass(frozen=True)
class Combo:
    """One point in the combination space: swept dimensions in canonical order."""

    values: tuple[tuple[Dimension, StrEnum], ...]

    @property
    def name(self) -> str:
        """Canonical combination string; deterministic, used as the pytest id."""
        return NAME_SEPARATOR.join(
            f"{dim.target}.{dim.tag}-{value.value}" for dim, value in self.values
        )

    @property
    def combo_id(self) -> str:
        """Deterministic content hash of the name: fixed-length, filesystem-safe,
        stable across runs (valid as a cross-run join key). combos.csv is the
        dereference map back to the name and dimensions."""
        return hashlib.sha256(self.name.encode()).hexdigest()[:16]


def _apply_stream_field(
    stream_name: str, field: str
) -> Callable[[CeceConfig, StrEnum], None]:
    def apply(config: CeceConfig, value: StrEnum) -> None:
        for stream in config.cece_data.streams:
            if stream.name == stream_name:
                setattr(stream, field, value)
                return
        raise ValueError(f"stream {stream_name!r} not found in config")

    return apply


def _apply_species_field(
    species: str, index: int, field: str
) -> Callable[[CeceConfig, StrEnum], None]:
    def apply(config: CeceConfig, value: StrEnum) -> None:
        entry = config.species[species][index]
        setattr(entry, field, value)
        if field == "vdist_method":
            if value is VdistMethod.height:
                entry.vdist_h_start, entry.vdist_h_end = _VDIST_HEIGHT_BOUNDS_M
            elif value is VdistMethod.pressure:
                entry.vdist_p_start, entry.vdist_p_end = _VDIST_PRESSURE_BOUNDS_PA

    return apply


def _sorted_values(values: list[StrEnum]) -> tuple[StrEnum, ...]:
    # Cannot change any combo's id (a name holds only its own values), but
    # makes enumeration, execution, and combos.csv order declaration-independent.
    return tuple(sorted(values, key=lambda value: value.value))


def _species_dimensions(
    sweep: Sweep, base_config: CeceConfig
) -> list[tuple[Dimension, tuple[StrEnum, ...]]]:
    if sweep.species is None:
        return []
    dimensions: list[tuple[Dimension, tuple[StrEnum, ...]]] = []
    for species in sorted(sweep.species):  # lexicographic, not declaration order
        if species not in base_config.species:
            raise ValueError(
                f"sweep targets species {species!r}, which is not in the base config "
                f"(species: {sorted(base_config.species)})"
            )
        entry_sweeps = sweep.species[species]
        n_entries = len(base_config.species[species])
        if len(entry_sweeps) > n_entries:
            raise ValueError(
                f"sweep for species {species!r} has {len(entry_sweeps)} entry blocks; "
                f"the base config has {n_entries} entries"
            )
        for index, entry_sweep in enumerate(entry_sweeps):
            target = species if index == 0 else f"{species}-{index}"
            for field, tag in _SPECIES_FIELDS:
                values = getattr(entry_sweep, field)
                if values:
                    dimensions.append(
                        (
                            Dimension(
                                target,
                                field,
                                tag,
                                _apply_species_field(species, index, field),
                            ),
                            _sorted_values(values),
                        )
                    )
    return dimensions


def _stream_dimensions(
    sweep: Sweep, base_config: CeceConfig
) -> list[tuple[Dimension, tuple[StrEnum, ...]]]:
    if sweep.cece_data is None:
        return []
    base_names = [stream.name for stream in base_config.cece_data.streams]
    dimensions: list[tuple[Dimension, tuple[StrEnum, ...]]] = []
    for stream_sweep in sorted(
        sweep.cece_data.streams, key=lambda s: s.name
    ):  # not declaration order
        if base_names.count(stream_sweep.name) != 1:
            raise ValueError(
                f"sweep targets stream {stream_sweep.name!r}, which must match exactly one "
                f"base-config stream (streams: {base_names})"
            )
        for field, tag in _STREAM_FIELDS:
            values = getattr(stream_sweep, field)
            if values:
                dimensions.append(
                    (
                        Dimension(
                            stream_sweep.name,
                            field,
                            tag,
                            _apply_stream_field(stream_sweep.name, field),
                        ),
                        _sorted_values(values),
                    )
                )
    return dimensions


def enumerate_combos(sweep: Sweep, base_config: CeceConfig) -> list[Combo]:
    """Cartesian product of the sweep's attached dimensions, validated against
    the base config (unknown selectors fail here, before any container runs).
    Canonical order: species targets first, then stream targets."""
    dimensions = _species_dimensions(sweep, base_config) + _stream_dimensions(
        sweep, base_config
    )
    if not dimensions:
        return []
    ordered = tuple(dimension for dimension, _ in dimensions)
    return [
        Combo(values=tuple(zip(ordered, chosen)))
        for chosen in itertools.product(*(values for _, values in dimensions))
    ]


def build_config(combo: Combo, output_directory: str, config_path: Path) -> CeceConfig:
    """Fresh base config loaded from config_path with the combo's enum values
    applied and NetCDF output pointed at the combo's own directory. Loading
    per combo keeps combinations isolated."""
    config = CeceConfig.from_yaml(config_path)
    for dimension, value in combo.values:
        dimension.apply(config, value)
    assert config.output is not None
    config.output.directory = output_directory
    return config


def write_combos_csv(combos: list[Combo], run_id: str, csv_path: Path) -> pd.DataFrame:
    """The dereference map from combo ids (directory names) back to the tested
    combinations: one row per swept dimension per combination."""
    columns = ["run_id", "combo_id", "name", "target", "field", "value"]
    rows = [
        {
            "run_id": run_id,
            "combo_id": combo.combo_id,
            "name": combo.name,
            "target": dimension.target,
            "field": dimension.field,
            "value": value.value,
        }
        for combo in combos
        for dimension, value in combo.values
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(csv_path, index=False)
    logger.info("wrote %s combination row(s) to %s", len(frame), csv_path)
    return frame
