import hashlib
from pathlib import Path

import pytest
import yaml

from combos import build_config, enumerate_combos, write_combos_csv
from models.cece_config import (
    CeceConfig,
    Mapalgo,
    Operation,
    OutputField,
    Taxmode,
    VdistMethod,
)
from models.suite_config import CeceDataSweep, SpeciesEntrySweep, StreamSweep, Sweep


@pytest.fixture()
def base_config(cece_config_path: Path) -> CeceConfig:
    return CeceConfig.from_yaml(cece_config_path)


@pytest.fixture()
def two_stream_config_path(tmp_path: Path, cece_config_path: Path) -> Path:
    """The maccity base config plus a second stream named AUXDATA."""
    content = yaml.safe_load(cece_config_path.read_text())
    second = dict(content["cece_data"]["streams"][0])
    second["name"] = "AUXDATA"
    content["cece_data"]["streams"].append(second)
    path = tmp_path / "two-stream.yaml"
    path.write_text(yaml.dump(content))
    return path


def _maccity_sweep() -> Sweep:
    return Sweep(
        cece_data=CeceDataSweep(
            streams=[
                StreamSweep(
                    name="MACCITY",
                    mapalgo=[Mapalgo.bilinear, Mapalgo.consd, Mapalgo.passthrough],
                )
            ]
        )
    )


def test_maccity_sweep_enumerates_three_qualified_combos(
    base_config: CeceConfig,
) -> None:
    combos = enumerate_combos(_maccity_sweep(), base_config)
    assert [combo.name for combo in combos] == [
        "MACCITY.map-bilinear",
        "MACCITY.map-consd",
        "MACCITY.map-passthrough",
    ]


def test_combo_ids_are_deterministic_content_hashes(base_config: CeceConfig) -> None:
    first = enumerate_combos(_maccity_sweep(), base_config)
    second = enumerate_combos(_maccity_sweep(), base_config)
    assert [combo.combo_id for combo in first] == [combo.combo_id for combo in second]
    for combo in first:
        assert combo.combo_id == hashlib.sha256(combo.name.encode()).hexdigest()[:16]
        assert len(combo.combo_id) == 16
        assert combo.combo_id == combo.combo_id.lower()


def test_normalization_declaration_order_never_matters(base_config: CeceConfig) -> None:
    # Same sweep, values reversed and species/stream blocks declared in a
    # different order, must enumerate byte-identical names and ids.
    tidy = Sweep(
        species={
            "co": [SpeciesEntrySweep(operation=[Operation.add, Operation.replace])]
        },
        cece_data=CeceDataSweep(
            streams=[
                StreamSweep(name="MACCITY", mapalgo=[Mapalgo.bilinear, Mapalgo.consd])
            ]
        ),
    )
    shuffled = Sweep(
        cece_data=CeceDataSweep(
            streams=[
                StreamSweep(name="MACCITY", mapalgo=[Mapalgo.consd, Mapalgo.bilinear])
            ]
        ),
        species={
            "co": [SpeciesEntrySweep(operation=[Operation.replace, Operation.add])]
        },
    )
    tidy_combos = enumerate_combos(tidy, base_config)
    shuffled_combos = enumerate_combos(shuffled, base_config)
    assert [combo.name for combo in tidy_combos] == [
        combo.name for combo in shuffled_combos
    ]
    assert [combo.combo_id for combo in tidy_combos] == [
        combo.combo_id for combo in shuffled_combos
    ]
    # Canonical order: species targets before stream targets.
    assert tidy_combos[0].name == "co.op-add__MACCITY.map-bilinear"


def test_empty_sweep_yields_no_combos(base_config: CeceConfig) -> None:
    assert enumerate_combos(Sweep(), base_config) == []


def test_field_attributes_round_trip_through_generated_configs(
    base_config: CeceConfig, cece_config_path: Path
) -> None:
    # The checked-in base config declares output attributes for co nested in
    # its fields entry; generated combo configs carry them to the driver.
    assert base_config.output is not None
    assert base_config.output.fields == [
        OutputField(
            name="co",
            attributes={
                "units": "kg m-2 s-1",
                "long_name": "carbon_monoxide_emission_flux",
            },
        )
    ]
    (combo,) = enumerate_combos(_single_consd_sweep(), base_config)
    generated = build_config(combo, output_directory=".", config_path=cece_config_path)
    assert generated.output is not None
    assert generated.output.fields == base_config.output.fields


def _single_consd_sweep() -> Sweep:
    return Sweep(
        cece_data=CeceDataSweep(
            streams=[StreamSweep(name="MACCITY", mapalgo=[Mapalgo.consd])]
        )
    )


def test_build_config_applies_to_named_non_first_stream(
    two_stream_config_path: Path,
) -> None:
    base = CeceConfig.from_yaml(two_stream_config_path)
    sweep = Sweep(
        cece_data=CeceDataSweep(
            streams=[StreamSweep(name="AUXDATA", mapalgo=[Mapalgo.nn])]
        )
    )
    (combo,) = enumerate_combos(sweep, base)
    assert combo.name == "AUXDATA.map-nn"

    config = build_config(
        combo, output_directory=".", config_path=two_stream_config_path
    )
    streams = {stream.name: stream for stream in config.cece_data.streams}
    assert streams["AUXDATA"].mapalgo is Mapalgo.nn
    assert streams["MACCITY"].mapalgo is Mapalgo.consd  # base value untouched


def test_stream_targets_sorted_lexicographically(two_stream_config_path: Path) -> None:
    base = CeceConfig.from_yaml(two_stream_config_path)
    sweep = Sweep(
        cece_data=CeceDataSweep(
            streams=[
                StreamSweep(name="MACCITY", mapalgo=[Mapalgo.consd]),
                StreamSweep(name="AUXDATA", taxmode=[Taxmode.extend]),
            ]
        )
    )
    (combo,) = enumerate_combos(sweep, base)
    assert combo.name == "AUXDATA.tax-extend__MACCITY.map-consd"


def test_build_config_supplies_vdist_companion_fields(
    base_config: CeceConfig, cece_config_path: Path
) -> None:
    sweep = Sweep(
        species={
            "co": [
                SpeciesEntrySweep(
                    vdist_method=[VdistMethod.height, VdistMethod.pressure]
                )
            ]
        }
    )
    height, pressure = enumerate_combos(sweep, base_config)
    assert height.name == "co.vd-HEIGHT"

    entry = build_config(
        height, output_directory=".", config_path=cece_config_path
    ).species["co"][0]
    assert entry.vdist_method is VdistMethod.height
    assert (entry.vdist_h_start, entry.vdist_h_end) == (0.0, 100.0)

    entry = build_config(
        pressure, output_directory=".", config_path=cece_config_path
    ).species["co"][0]
    assert entry.vdist_method is VdistMethod.pressure
    assert (entry.vdist_p_start, entry.vdist_p_end) == (100000.0, 90000.0)


def test_unknown_stream_selector_rejected(base_config: CeceConfig) -> None:
    sweep = Sweep(
        cece_data=CeceDataSweep(
            streams=[StreamSweep(name="NOPE", mapalgo=[Mapalgo.consd])]
        )
    )
    with pytest.raises(ValueError, match="NOPE"):
        enumerate_combos(sweep, base_config)


def test_unknown_species_selector_rejected(base_config: CeceConfig) -> None:
    sweep = Sweep(species={"nox": [SpeciesEntrySweep(operation=[Operation.add])]})
    with pytest.raises(ValueError, match="nox"):
        enumerate_combos(sweep, base_config)


def test_oversized_species_entry_list_rejected(base_config: CeceConfig) -> None:
    sweep = Sweep(
        species={
            "co": [
                SpeciesEntrySweep(operation=[Operation.add]),
                SpeciesEntrySweep(operation=[Operation.replace]),
            ]
        }
    )
    with pytest.raises(ValueError, match="entry blocks"):
        enumerate_combos(sweep, base_config)


def test_write_combos_csv_dereferences_directories(
    tmp_path: Path, base_config: CeceConfig
) -> None:
    combos = enumerate_combos(_maccity_sweep(), base_config)
    csv_path = tmp_path / "combos.csv"
    frame = write_combos_csv(
        combos, run_id="01JZZZZZZZZZZZZZZZZZZZZZZZ", csv_path=csv_path
    )

    assert csv_path.is_file()
    assert list(frame.columns) == [
        "run_id",
        "combo_id",
        "name",
        "target",
        "field",
        "value",
    ]
    assert len(frame) == 3  # one dimension per combo here
    consd = frame[frame["combo_id"] == combos[1].combo_id]
    assert consd["name"].iloc[0] == "MACCITY.map-consd"
    assert (
        consd["target"].iloc[0],
        consd["field"].iloc[0],
        consd["value"].iloc[0],
    ) == (
        "MACCITY",
        "mapalgo",
        "consd",
    )
