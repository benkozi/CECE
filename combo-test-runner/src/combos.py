"""Sweep -> combinations: enumeration, naming, and driver-config generation.

All generated configs are built as CeceConfig instances and written only via
CeceConfig.to_yaml() so every config the driver receives has passed pydantic
validation.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from models.cece_config import (
    Category,
    CeceConfig,
    Mapalgo,
    Operation,
    SpeciesEntry,
    Stream,
    Taxmode,
    Tintalgo,
    VdistMethod,
)
from models.suite_config import Sweep

# Companion vdist bounds required for a valid config when sweeping VdistMethod.
_VDIST_HEIGHT_BOUNDS_M = (0.0, 100.0)
_VDIST_PRESSURE_BOUNDS_PA = (100000.0, 90000.0)


def _first_entry(config: CeceConfig) -> SpeciesEntry:
    return next(iter(config.species.values()))[0]


def _first_stream(config: CeceConfig) -> Stream:
    return config.cece_data.streams[0]


def _apply_operation(config: CeceConfig, value: StrEnum) -> None:
    _first_entry(config).operation = Operation(value)


def _apply_category(config: CeceConfig, value: StrEnum) -> None:
    _first_entry(config).category = Category(value)


def _apply_vdist_method(config: CeceConfig, value: StrEnum) -> None:
    entry = _first_entry(config)
    entry.vdist_method = VdistMethod(value)
    if entry.vdist_method is VdistMethod.height:
        entry.vdist_h_start, entry.vdist_h_end = _VDIST_HEIGHT_BOUNDS_M
    elif entry.vdist_method is VdistMethod.pressure:
        entry.vdist_p_start, entry.vdist_p_end = _VDIST_PRESSURE_BOUNDS_PA


def _apply_taxmode(config: CeceConfig, value: StrEnum) -> None:
    _first_stream(config).taxmode = Taxmode(value)


def _apply_tintalgo(config: CeceConfig, value: StrEnum) -> None:
    _first_stream(config).tintalgo = Tintalgo(value)


def _apply_mapalgo(config: CeceConfig, value: StrEnum) -> None:
    _first_stream(config).mapalgo = Mapalgo(value)


@dataclass(frozen=True)
class Dimension:
    key: str  # field name on Sweep
    abbrev: str  # short tag used in combo names
    apply: Callable[[CeceConfig, StrEnum], None]


# Canonical order: fixes both combo-name layout and enumeration order.
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("operation", "op", _apply_operation),
    Dimension("category", "cat", _apply_category),
    Dimension("vdist_method", "vd", _apply_vdist_method),
    Dimension("taxmode", "tax", _apply_taxmode),
    Dimension("tintalgo", "tint", _apply_tintalgo),
    Dimension("mapalgo", "map", _apply_mapalgo),
)


@dataclass(frozen=True)
class Combo:
    """One point in the combination space: swept dimensions in canonical order."""

    values: tuple[tuple[Dimension, StrEnum], ...]

    @property
    def name(self) -> str:
        return "_".join(f"{dim.abbrev}-{value.value}" for dim, value in self.values)


def enumerate_combos(sweep: Sweep) -> list[Combo]:
    swept = [(dim, getattr(sweep, dim.key)) for dim in DIMENSIONS if getattr(sweep, dim.key)]
    if not swept:
        return []
    dims = tuple(dim for dim, _ in swept)
    return [
        Combo(values=tuple(zip(dims, chosen)))
        for chosen in itertools.product(*(values for _, values in swept))
    ]


def build_config(combo: Combo, output_directory: str, config_path: Path) -> CeceConfig:
    """Fresh base config loaded from config_path with the combo's enum values
    applied and NetCDF output pointed at the combo's own directory. Loading
    per combo keeps combinations isolated."""
    config = CeceConfig.from_yaml(config_path)
    for dim, value in combo.values:
        dim.apply(config, value)
    assert config.output is not None
    config.output.directory = output_directory
    return config
