from pathlib import Path

from combos import build_config, enumerate_combos
from models.cece_config import Mapalgo, Operation, VdistMethod
from models.suite_config import Sweep


def test_maccity_sweep_enumerates_three_combos() -> None:
    sweep = Sweep(mapalgo=[Mapalgo.bilinear, Mapalgo.consd, Mapalgo.passthrough])
    assert [combo.name for combo in enumerate_combos(sweep)] == [
        "map-bilinear",
        "map-consd",
        "map-passthrough",
    ]


def test_multi_dimension_sweep_is_cartesian_product_in_canonical_order() -> None:
    sweep = Sweep(mapalgo=[Mapalgo.consd, Mapalgo.bilinear], operation=[Operation.add, Operation.replace])
    # operation precedes mapalgo in canonical order regardless of Sweep field order
    assert [combo.name for combo in enumerate_combos(sweep)] == [
        "op-add_map-consd",
        "op-add_map-bilinear",
        "op-replace_map-consd",
        "op-replace_map-bilinear",
    ]


def test_empty_sweep_yields_no_combos() -> None:
    assert enumerate_combos(Sweep()) == []


def test_build_config_applies_mapalgo_and_output_directory(cece_config_path: Path) -> None:
    combo = enumerate_combos(Sweep(mapalgo=[Mapalgo.bilinear]))[0]
    config = build_config(combo, output_directory="/combo_runs/map-bilinear", config_path=cece_config_path)
    assert config.cece_data.streams[0].mapalgo is Mapalgo.bilinear
    assert config.output is not None
    assert config.output.directory == "/combo_runs/map-bilinear"


def test_build_config_supplies_vdist_companion_fields(cece_config_path: Path) -> None:
    height, pressure = enumerate_combos(Sweep(vdist_method=[VdistMethod.height, VdistMethod.pressure]))

    entry = build_config(height, output_directory=".", config_path=cece_config_path).species["co"][0]
    assert entry.vdist_method is VdistMethod.height
    assert (entry.vdist_h_start, entry.vdist_h_end) == (0.0, 100.0)

    entry = build_config(pressure, output_directory=".", config_path=cece_config_path).species["co"][0]
    assert entry.vdist_method is VdistMethod.pressure
    assert (entry.vdist_p_start, entry.vdist_p_end) == (100000.0, 90000.0)


def test_build_config_isolates_combos(cece_config_path: Path) -> None:
    first, second = enumerate_combos(Sweep(mapalgo=[Mapalgo.consd, Mapalgo.nn]))
    config_first = build_config(first, output_directory="a", config_path=cece_config_path)
    config_second = build_config(second, output_directory="b", config_path=cece_config_path)
    assert config_first.cece_data.streams[0].mapalgo is Mapalgo.consd
    assert config_second.cece_data.streams[0].mapalgo is Mapalgo.nn
    assert config_first.output is not None and config_first.output.directory == "a"
