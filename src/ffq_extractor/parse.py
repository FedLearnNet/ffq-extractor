"""Parse FFQ Excel matrix into Nutrition rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from openpyxl import load_workbook

from .frequencies import (
    frequency_code_for_header,
    is_accepted_mark,
    is_blank_cell,
    normalize_header,
)
from .mapping import FoodMapping, load_food_mapping

OUTPUT_COLUMNS = [
    "Unique Patient ID",
    "Questionnaire date",
    "Portion size",
    "Frequency consumption",
    "Food group",
    "Food subgroup",
    "Food item",
]

FREQ_COL_START = 1  # column B (0-indexed)
FREQ_COL_END = 11  # exclusive → columns B–K


@dataclass
class NutritionRow:
    unique_patient_id: str
    questionnaire_date: str
    portion_size: str
    frequency_consumption: str
    food_group: str
    food_subgroup: str
    food_item: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "Unique Patient ID": self.unique_patient_id,
            "Questionnaire date": self.questionnaire_date,
            "Portion size": self.portion_size,
            "Frequency consumption": self.frequency_consumption,
            "Food group": self.food_group,
            "Food subgroup": self.food_subgroup,
            "Food item": self.food_item,
        }


@dataclass
class ExtractResult:
    rows: List[NutritionRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    patient_id: str = ""
    questionnaire_date: str = ""
    marked_count: int = 0
    omitted_never: int = 0
    omitted_blank: int = 0
    omitted_na_mapping: int = 0
    omitted_odd_mark: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


class ExtractError(Exception):
    """Fatal FFQ extraction error."""


def _format_date(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text


def _parse_portion(section_label: str) -> str:
    if " - " not in section_label:
        # e.g. "The following on bread or vegetables (teaspoon):"
        lowered = section_label.lower()
        if "teaspoon" in lowered:
            return "teaspoon"
        return ""
    return section_label.split(" - ", 1)[1].strip()


def resolve_patient_id(a2: object, b2: object, a3: object, b3: object) -> str:
    """
    Prefer B3, else B2, else A3 if it is more than bare 'MAI_'.
    """
    for candidate in (b3, b2):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()

    a3_text = "" if a3 is None else str(a3).strip()
    if a3_text and a3_text.rstrip("_").upper() != "MAI":
        # Keep full value (e.g. MAI_12345)
        return a3_text

    # If A2 somehow holds the id after the label
    a2_text = "" if a2 is None else str(a2).strip()
    label = "participant study number:"
    if a2_text.lower().startswith(label):
        remainder = a2_text[len(label) :].strip()
        if remainder:
            return remainder

    raise ExtractError(
        "Patient ID not found. Expected a value in B3, B2, or A3 "
        "(beyond bare 'MAI_')."
    )


def _is_section_header(row: Sequence[object]) -> bool:
    if len(row) <= FREQ_COL_START:
        return False
    return normalize_header(row[FREQ_COL_START]) == "never"


def _extract_frequency_headers(row: Sequence[object]) -> List[object]:
    return list(row[FREQ_COL_START:FREQ_COL_END])


def _select_frequency(
    food_item: str,
    cells: Sequence[object],
    headers: Sequence[object],
    result: ExtractResult,
    *,
    strict: bool,
) -> Optional[str]:
    """Return schema frequency code or None if the row should be omitted."""
    marked_indexes: List[int] = []
    odd_marks: List[str] = []

    for idx, cell in enumerate(cells):
        if is_blank_cell(cell):
            continue
        if is_accepted_mark(cell):
            marked_indexes.append(idx)
        else:
            odd_marks.append(str(cell).strip())

    if len(marked_indexes) > 1:
        msg = (
            f"Multiple frequency marks for food item {food_item!r} "
            f"at columns {[headers[i] for i in marked_indexes]!r}"
        )
        result.errors.append(msg)
        return None

    if odd_marks and not marked_indexes:
        msg = (
            f"Unrecognized mark(s) {odd_marks!r} for food item {food_item!r}; "
            "row omitted"
        )
        result.warnings.append(msg)
        result.omitted_odd_mark += 1
        if strict:
            result.errors.append(msg)
        return None

    if odd_marks and marked_indexes:
        msg = (
            f"Unrecognized extra mark(s) {odd_marks!r} alongside a valid mark "
            f"for food item {food_item!r}"
        )
        result.warnings.append(msg)
        if strict:
            result.errors.append(msg)

    if not marked_indexes:
        result.omitted_blank += 1
        return None

    header = headers[marked_indexes[0]]
    if normalize_header(header) == "never":
        result.omitted_never += 1
        return None

    try:
        code = frequency_code_for_header(header)
    except ValueError as exc:
        result.errors.append(str(exc))
        return None

    if code is None:
        result.omitted_never += 1
        return None
    return code


def extract_ffq(
    workbook_path: Union[str, Path],
    mapping_path: Optional[Union[str, Path]] = None,
    *,
    sheet_name: str = "Sheet1",
    strict: bool = False,
    food_mapping: Optional[Dict[str, FoodMapping]] = None,
    read_only: bool = False,
) -> ExtractResult:
    """
    Read an FFQ workbook and return Nutrition rows + diagnostics.

    Use read_only=True for batch/ZIP workloads (lower memory).
    """
    path = Path(workbook_path)
    mapping = food_mapping if food_mapping is not None else load_food_mapping(mapping_path)
    result = ExtractResult()

    wb = load_workbook(path, data_only=True, read_only=read_only)
    try:
        if sheet_name not in wb.sheetnames:
            raise ExtractError(
                f"Sheet {sheet_name!r} not found. Available: {wb.sheetnames}"
            )
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if len(rows) < 3:
        raise ExtractError("FFQ sheet has fewer than 3 rows")

    questionnaire_date = _format_date(rows[0][0] if rows[0] else None)
    result.questionnaire_date = questionnaire_date

    a2 = rows[1][0] if len(rows[1]) > 0 else None
    b2 = rows[1][1] if len(rows[1]) > 1 else None
    a3 = rows[2][0] if len(rows[2]) > 0 else None
    b3 = rows[2][1] if len(rows[2]) > 1 else None

    try:
        patient_id = resolve_patient_id(a2, b2, a3, b3)
    except ExtractError as exc:
        result.errors.append(str(exc))
        return result
    result.patient_id = patient_id

    current_portion = ""
    current_headers: List[object] = []

    for row_idx, row in enumerate(rows[3:], start=4):
        if not row or row[0] is None or not str(row[0]).strip():
            continue
        label = str(row[0]).strip()

        if _is_section_header(row):
            current_portion = _parse_portion(label)
            current_headers = _extract_frequency_headers(row)
            continue

        if not current_headers:
            result.warnings.append(
                f"Row {row_idx}: food item {label!r} before any section header; skipped"
            )
            continue

        food = mapping.get(label)
        if food is None:
            result.errors.append(
                f"Row {row_idx}: food item {label!r} not found in mapping file"
            )
            continue

        cells = list(row[FREQ_COL_START:FREQ_COL_END])
        # Pad if short
        if len(cells) < len(current_headers):
            cells.extend([None] * (len(current_headers) - len(cells)))

        code = _select_frequency(
            label, cells, current_headers, result, strict=strict
        )
        if code is None:
            continue

        if food.is_na:
            msg = (
                f"Row {row_idx}: food item {label!r} mapped to NA "
                f"({food.comment or 'not in French questionnaire'}); omitted"
            )
            result.warnings.append(msg)
            result.omitted_na_mapping += 1
            if strict:
                result.errors.append(msg)
            continue

        result.marked_count += 1
        result.rows.append(
            NutritionRow(
                unique_patient_id=patient_id,
                questionnaire_date=questionnaire_date,
                portion_size=current_portion,
                frequency_consumption=code,
                food_group=food.food_group,
                food_subgroup=food.food_subgroup,
                food_item=food.food_item,
            )
        )

    return result
