from pathlib import PurePosixPath

from conftest import ComboRoots

from combos import Combo
from runner import run_driver
from settings import Settings


def test_driver_combo(
    combo: Combo,
    generated_yamls: dict[str, PurePosixPath],
    combo_roots: ComboRoots,
    settings: Settings,
    run_timeout_s: int,
) -> None:
    out_path = combo_roots.host / combo.name / f"{combo.name}.out"
    run_driver(
        settings,
        container_yaml=generated_yamls[combo.name],
        out_path=out_path,
        timeout_s=run_timeout_s,
        output_mount=combo_roots.output_mount,
    )
