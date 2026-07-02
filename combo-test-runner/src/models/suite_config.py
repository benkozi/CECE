from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from models.cece_config import Category, Mapalgo, Operation, Taxmode, Tintalgo, VdistMethod


class Sweep(BaseModel):
    """Enum values to sweep. Enums left unset are not swept and stay at their
    base-config values; the combination space is the cartesian product of the
    listed values."""

    operation: list[Operation] | None = Field(None, min_length=1)
    category: list[Category] | None = Field(None, min_length=1)
    vdist_method: list[VdistMethod] | None = Field(None, min_length=1)
    taxmode: list[Taxmode] | None = Field(None, min_length=1)
    tintalgo: list[Tintalgo] | None = Field(None, min_length=1)
    mapalgo: list[Mapalgo] | None = Field(None, min_length=1)


class SuiteConfig(BaseModel):
    sweep: Sweep = Field(description="Enum dimensions and values defining the combination space")

    @classmethod
    def from_yaml(cls, path: Path) -> SuiteConfig:
        with open(path) as f:
            return cls.model_validate(yaml.safe_load(f))
