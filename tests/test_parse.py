from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from ffq_extractor.export import rows_to_dataframe, write_csv
from ffq_extractor.mapping import load_food_mapping
from ffq_extractor.parse import (
    OUTPUT_COLUMNS,
    extract_ffq,
    resolve_patient_id,
    _parse_portion,
)

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data" / "Matching_nutritional_variables.xlsx"
BLANK = ROOT / "tests" / "fixtures" / "blank_ffq.xlsx"

FREQ_HEADERS = [
    "Never",
    "Less than once a month",
    "Once a month",
    "Once a week",
    "Twice a week",
    "5 times a week",
    "Once a day",
    "Twice a day",
    "4 times a day",
    "6 or more times a day",
]


def test_resolve_patient_id_prefers_b3():
    assert resolve_patient_id("Participant study number: ", None, "MAI_", "MAI_42") == "MAI_42"


def test_resolve_patient_id_falls_back_to_b2():
    assert resolve_patient_id("Participant study number: ", "MAI_7", "MAI_", None) == "MAI_7"


def test_resolve_patient_id_from_a3_suffix():
    assert resolve_patient_id("Participant study number: ", None, "MAI_99", None) == "MAI_99"


def test_resolve_patient_id_missing():
    with pytest.raises(Exception):
        resolve_patient_id("Participant study number: ", None, "MAI_", None)


@pytest.mark.parametrize(
    "label,expected",
    [
        (
            "Meat, fish, poultry - Medium serving (size deck of cards)",
            "Medium serving (size deck of cards)",
        ),
        ("Dairy products and fat", ""),
        ("The following on bread or vegetables (teaspoon):", "teaspoon"),
    ],
)
def test_parse_portion(label, expected):
    assert _parse_portion(label) == expected


def _mark_row(food: str, header_name: str):
    cells = [None] * 10
    cells[FREQ_HEADERS.index(header_name)] = "X"
    return (food, *cells)


def build_synthetic_ffq(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([datetime(2026, 9, 1)])
    ws.append(["Participant study number: ", None])
    ws.append(["MAI_", "MAI_TEST01"])
    ws.append(
        (
            "Meat, fish, poultry - Medium serving (size deck of cards)",
            *FREQ_HEADERS,
            "Comment",
        )
    )
    # marked 6+/D
    ws.append(_mark_row("Beef (roast / steak)", "6 or more times a day"))
    # Never marked → omit
    ws.append(_mark_row("Beef: stew", "Never"))
    # blank → omit
    ws.append(("Pork (roast / chops / escalopes)", *([None] * 10)))
    # multi-mark → error
    multi = [None] * 10
    multi[FREQ_HEADERS.index("Once a week")] = "X"
    multi[FREQ_HEADERS.index("Once a day")] = "X"
    ws.append(("Lamb (roast / chops / stew)", *multi))
    # odd mark → omit with warning
    odd = [None] * 10
    odd[FREQ_HEADERS.index("Once a month")] = "NA"
    ws.append(("Bacon / Ham", *odd))

    ws.append(
        (
            "Potatoes, rice and pasta - Medium serving = a cupful",
            *FREQ_HEADERS,
            "Comment",
        )
    )
    ws.append(_mark_row("Mashed potatoes", "Once a month"))

    # NA-mapped item
    ws.append(
        (
            "Soups, sauces and spreads",
            *FREQ_HEADERS,
            "Comment",
        )
    )
    ws.append(_mark_row("Pickles, chutney (tablespoon)", "Once a week"))

    wb.save(path)
    return path


def test_blank_ffq_requires_patient_id():
    result = extract_ffq(BLANK, mapping_path=MAPPING)
    assert not result.ok
    assert any("Patient ID" in e for e in result.errors)


def test_blank_ffq_with_injected_patient(tmp_path):
    from openpyxl import load_workbook

    out = tmp_path / "blank_with_id.xlsx"
    wb = load_workbook(BLANK)
    ws = wb["Sheet1"]
    ws["B3"] = "MAI_BLANK"
    wb.save(out)
    wb.close()

    result = extract_ffq(out, mapping_path=MAPPING)
    assert result.ok
    assert result.patient_id == "MAI_BLANK"
    assert result.rows == []
    df = rows_to_dataframe(result.rows)
    assert list(df.columns) == OUTPUT_COLUMNS


def test_synthetic_extraction(tmp_path):
    xlsx = build_synthetic_ffq(tmp_path / "synthetic.xlsx")
    result = extract_ffq(xlsx, mapping_path=MAPPING)

    assert any("Multiple frequency marks" in e for e in result.errors)
    assert result.omitted_never == 1
    assert result.omitted_odd_mark == 1
    assert result.omitted_na_mapping == 1

    # Despite multi-mark error, other valid rows are collected
    by_item = {r.food_item: r for r in result.rows}
    assert by_item["Beef (roast / steak)"].frequency_consumption == "6+/D"
    assert (
        by_item["Beef (roast / steak)"].portion_size
        == "Medium serving (size deck of cards)"
    )
    assert by_item["Beef (roast / steak)"].food_group == (
        "Meat/fish/eggs and substitutes"
    )
    assert by_item["Beef (roast / steak)"].food_subgroup == "Meat excluding offal"

    mashed = by_item["Mashed potatoes"]
    assert mashed.frequency_consumption == "1/M"
    assert mashed.portion_size == "Medium serving = a cupful"
    assert mashed.food_group == "Starchy foods"
    assert mashed.food_subgroup == "Potatoe"
    assert mashed.unique_patient_id == "MAI_TEST01"
    assert mashed.questionnaire_date == "2026-09-01"

    assert "Pickles, chutney (tablespoon)" not in by_item
    assert "Beef: stew" not in by_item


def test_write_csv_golden(tmp_path):
    xlsx = build_synthetic_ffq(tmp_path / "synthetic.xlsx")
    # Use a mapping-only success path: filter by running without collecting multi-error halt
    # CLI fails on errors; library still returns rows + errors. write_csv of successful subset:
    result = extract_ffq(xlsx, mapping_path=MAPPING)
    # Drop error-causing case by rebuilding without multi-mark
    csv_path = write_csv(result.rows, tmp_path / "out.csv")
    df = pd.read_csv(csv_path)
    assert list(df.columns) == OUTPUT_COLUMNS
    assert set(df["Food item"]) == {"Beef (roast / steak)", "Mashed potatoes"}


def test_strict_na_becomes_error(tmp_path):
    xlsx = build_synthetic_ffq(tmp_path / "synthetic.xlsx")
    result = extract_ffq(xlsx, mapping_path=MAPPING, strict=True)
    assert any("mapped to NA" in e for e in result.errors)


def test_mapping_loaded_once_external():
    mapping = load_food_mapping(MAPPING)
    assert "Beef (roast / steak)" in mapping
