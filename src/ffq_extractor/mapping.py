"""Load food item → group/subgroup mapping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union

from openpyxl import load_workbook

DEFAULT_MAPPING_FILENAME = (
    "Matching_nutritional_variables.xlsx"
)


@dataclass(frozen=True)
class FoodMapping:
    food_item: str
    food_group: str
    food_subgroup: str
    comment: str = ""

    @property
    def is_na(self) -> bool:
        return (
            self.food_group.upper() == "NA"
            or self.food_subgroup.upper() == "NA"
        )


def default_mapping_path() -> Path:
    """Vendored mapping next to the package data/ directory in the repo."""
    # Prefer package-adjacent repo data/; fall back to sibling of src tree.
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "data" / DEFAULT_MAPPING_FILENAME,  # repo root (editable)
        here.parents[1] / "data" / DEFAULT_MAPPING_FILENAME,
        Path.cwd() / "data" / DEFAULT_MAPPING_FILENAME,
        Path("/app/data") / DEFAULT_MAPPING_FILENAME,  # container layout
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"Default mapping file not found. Looked in: "
        + ", ".join(str(c) for c in candidates)
    )


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_food_mapping(
    path: Optional[Union[str, Path]] = None,
) -> Dict[str, FoodMapping]:
    """
    Load food-item rows from the matching workbook.

    Uses translated English group/subgroup columns. Section header rows
    (empty group/subgroup) are skipped. Trailing spaces are stripped.
    """
    mapping_path = Path(path) if path else default_mapping_path()
    wb = load_workbook(mapping_path, data_only=True, read_only=True)
    try:
        ws = wb.active
        result: Dict[str, FoodMapping] = {}
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if i == 1 or not row:
                continue
            item = _clean(row[0] if len(row) > 0 else None)
            if not item:
                continue
            group = _clean(row[3] if len(row) > 3 else None)
            subgroup = _clean(row[4] if len(row) > 4 else None)
            comment = _clean(row[5] if len(row) > 5 else None)
            # Section headers have no translated group/subgroup
            if not group and not subgroup:
                continue
            result[item] = FoodMapping(
                food_item=item,
                food_group=group,
                food_subgroup=subgroup,
                comment=comment,
            )
        return result
    finally:
        wb.close()
