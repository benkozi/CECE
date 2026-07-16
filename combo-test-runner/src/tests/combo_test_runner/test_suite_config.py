import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from models.cece_config import CeceConfig
from models.suite_config import (
    AttributesAssertion,
    RunManifest,
    SpeciesAssertions,
    SuiteConfig,
)


def test_config_path_resolves_relative_to_suite_file(suite_path: Path) -> None:
    suite = SuiteConfig.from_yaml(suite_path)
    assert suite.name == "simple-maccity"
    assert (
        suite.config_path
        == (suite_path.parent / ".." / "cece" / "simple-maccity.yaml").resolve()
    )
    assert suite.config_path.is_file()


def test_config_search_path_prepends_whole_path(
    tmp_path: Path, suite_path: Path, cece_config_path: Path
) -> None:
    # Mirror the config tree layout under a search directory; the suite's
    # ../cece reference walks out of the search dir (accepted behavior).
    (tmp_path / "suite").mkdir()
    (tmp_path / "cece").mkdir()
    shutil.copy(suite_path, tmp_path / "suite" / "copied-suite.yaml")
    shutil.copy(cece_config_path, tmp_path / "cece" / "simple-maccity.yaml")

    suite = SuiteConfig.from_yaml(
        tmp_path / "suite" / "copied-suite.yaml", config_search_path=tmp_path / "suite"
    )
    assert suite.config_path == (tmp_path / "cece" / "simple-maccity.yaml").resolve()


def test_absolute_config_path_ignores_search_path(
    tmp_path: Path, cece_config_path: Path
) -> None:
    suite_file = tmp_path / "abs-suite.yaml"
    suite_file.write_text(
        f"name: inline-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file, config_search_path=tmp_path)
    assert suite.config_path == cece_config_path


def test_missing_config_path_raises(tmp_path: Path) -> None:
    suite_file = tmp_path / "broken-suite.yaml"
    suite_file.write_text(
        "name: broken-suite\nconfig_path: nope.yaml\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        SuiteConfig.from_yaml(suite_file)


def test_assertions_default_when_section_absent(
    tmp_path: Path, cece_config_path: Path
) -> None:
    suite_file = tmp_path / "no-assertions-suite.yaml"
    suite_file.write_text(
        f"name: inline-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file)
    assert suite.assertions.expected_nc_file_count is None
    assert suite.assertions.validate_filenames is True


def test_invalid_sweep_value_fails_at_load(
    tmp_path: Path, cece_config_path: Path
) -> None:
    suite_file = tmp_path / "typo-suite.yaml"
    suite_file.write_text(
        f"name: inline-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [bilinnear]\n"
    )
    with pytest.raises(ValidationError):
        SuiteConfig.from_yaml(suite_file)


def test_missing_suite_name_rejected(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "nameless-suite.yaml"
    suite_file.write_text(
        f"config_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    with pytest.raises(ValidationError, match="name"):
        SuiteConfig.from_yaml(suite_file)


def test_malformed_suite_name_rejected(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "badname-suite.yaml"
    suite_file.write_text(
        f"name: Simple Maccity!\nconfig_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    with pytest.raises(ValidationError, match="name"):
        SuiteConfig.from_yaml(suite_file)


def test_species_assertions_defaults() -> None:
    assert SpeciesAssertions().attributes is None  # omitted -> no attribute test
    assertion = AttributesAssertion()
    assert assertion.exact is True
    assert assertion.expected == {}


def test_species_attributes_block_parses(
    tmp_path: Path, cece_config_path: Path
) -> None:
    suite_file = tmp_path / "species-suite.yaml"
    suite_file.write_text(
        f"name: species-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\n"
        "assertions:\n  species:\n    co:\n      attributes:\n        exact: false\n"
        "        expected:\n          units: kg m-2 s-1\n          history: null\n"
        "sweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file)
    assert suite.assertions.species is not None
    attributes = suite.assertions.species["co"].attributes
    assert attributes is not None
    assert attributes.exact is False
    assert attributes.expected == {"units": "kg m-2 s-1", "history": None}


def test_old_units_schema_rejected(tmp_path: Path, cece_config_path: Path) -> None:
    # The units-only first cut (species.<name>.units) is a removed schema.
    suite_file = tmp_path / "old-units-suite.yaml"
    suite_file.write_text(
        f"name: old-units\nconfig_path: {cece_config_path}\ntimeout_s: 5\n"
        "assertions:\n  species:\n    co:\n      units: kg m-2 s-1\n"
        "sweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    with pytest.raises(ValidationError, match="units"):
        SuiteConfig.from_yaml(suite_file)


def test_old_flat_sweep_format_rejected(tmp_path: Path, cece_config_path: Path) -> None:
    # Pre-attachment flat sweeps (enum lists directly under sweep:) are a
    # removed schema; StrictModel rejects the unknown keys loudly.
    suite_file = tmp_path / "flat-suite.yaml"
    suite_file.write_text(
        f"name: flat-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\n"
        "sweep:\n  mapalgo: [bilinear, consd]\n"
    )
    with pytest.raises(ValidationError, match="mapalgo"):
        SuiteConfig.from_yaml(suite_file)


def test_duplicate_sweep_values_rejected(
    tmp_path: Path, cece_config_path: Path
) -> None:
    suite_file = tmp_path / "dup-suite.yaml"
    suite_file.write_text(
        f"name: dup-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\n"
        "sweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd, consd]\n"
    )
    with pytest.raises(ValidationError, match="duplicate values"):
        SuiteConfig.from_yaml(suite_file)


def test_unknown_suite_key_rejected(tmp_path: Path, cece_config_path: Path) -> None:
    # ulid is runtime-only and must never come from configuration; unknown
    # keys generally fail loudly rather than being silently dropped.
    suite_file = tmp_path / "ulid-suite.yaml"
    suite_file.write_text(
        f"name: inline-suite\nconfig_path: {cece_config_path}\nulid: 01JZZ\ntimeout_s: 5\nsweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    with pytest.raises(ValidationError, match="ulid"):
        SuiteConfig.from_yaml(suite_file)


def test_output_fields_mixed_shorthand_and_map_entries(
    tmp_path: Path, cece_config_path: Path
) -> None:
    # An output.fields entry is a plain string (shorthand: no configured
    # attributes) or a {name, attributes} map — matching the driver schema.
    from models.cece_config import OutputField

    content = yaml.safe_load(cece_config_path.read_text())
    content["output"]["fields"] = [
        {"name": "co", "attributes": {"units": "kg m-2 s-1"}},
        "nox",
    ]
    config_file = tmp_path / "mixed-fields-config.yaml"
    config_file.write_text(yaml.dump(content))

    config = CeceConfig.from_yaml(config_file)
    assert config.output is not None
    assert config.output.fields == [
        OutputField(name="co", attributes={"units": "kg m-2 s-1"}),
        "nox",
    ]

    # Round-trips to the driver schema: shorthand stays a scalar.
    round_trip = tmp_path / "round-trip.yaml"
    config.to_yaml(round_trip)
    dumped = yaml.safe_load(round_trip.read_text())
    assert dumped["output"]["fields"] == [
        {"name": "co", "attributes": {"units": "kg m-2 s-1"}},
        "nox",
    ]


def test_unknown_nested_cece_config_key_rejected(
    tmp_path: Path, cece_config_path: Path
) -> None:
    content = yaml.safe_load(cece_config_path.read_text())
    content["driver"]["bogus_knob"] = 1
    config_file = tmp_path / "bogus-config.yaml"
    config_file.write_text(yaml.dump(content))
    with pytest.raises(ValidationError, match="bogus_knob"):
        CeceConfig.from_yaml(config_file)


def test_run_manifest_round_trips_through_yaml(
    tmp_path: Path, suite_path: Path
) -> None:
    suite = SuiteConfig.from_yaml(suite_path)
    manifest = RunManifest(run_id="01JZZZZZZZZZZZZZZZZZZZZZZZ", suite=suite)
    manifest_path = tmp_path / "run.yaml"
    manifest.to_yaml(manifest_path)

    reloaded = RunManifest.model_validate(yaml.safe_load(manifest_path.read_text()))
    assert reloaded.run_id == manifest.run_id
    assert reloaded.suite.config_path == suite.config_path
    assert reloaded.suite.sweep == suite.sweep
