"""Export Nutrition rows to CSV (streaming / merge-friendly)."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, TextIO, Union

import pandas as pd

from .parse import OUTPUT_COLUMNS, NutritionRow

BUFFER_SIZE = 8 * 1024 * 1024  # 8 MiB


def rows_to_dataframe(rows: Iterable[NutritionRow]) -> pd.DataFrame:
    records: List[dict] = [row.as_dict() for row in rows]
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)


def write_csv(
    rows: Iterable[NutritionRow],
    output_path: Union[str, Path],
) -> Path:
    """Write all rows at once (single-file / tests). Prefer CsvRowWriter for bulk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


class CsvRowWriter:
    """Buffered CSV writer that streams rows without holding the full dataset."""

    def __init__(self, output_path: Union[str, Path], *, write_header: bool = True):
        self.path = Path(output_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle: Optional[TextIO] = self.path.open(
            "w", newline="", encoding="utf-8", buffering=BUFFER_SIZE
        )
        self._writer = csv.DictWriter(self._handle, fieldnames=OUTPUT_COLUMNS)
        self.rows_written = 0
        if write_header:
            self._writer.writeheader()

    def write_rows(self, rows: Iterable[NutritionRow]) -> int:
        count = 0
        for row in rows:
            self._writer.writerow(row.as_dict())
            count += 1
        self.rows_written += count
        return count

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "CsvRowWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def write_part_csv(
    rows: Iterable[NutritionRow],
    part_path: Union[str, Path],
) -> Path:
    """Write a headerless part file for later merge."""
    path = Path(part_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def init_output_csv(output_path: Union[str, Path]) -> Path:
    """Create final CSV with header only."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS).writeheader()
    return path


def append_csv_part(part_path: Union[str, Path], output_path: Union[str, Path]) -> int:
    """
    Append a headerless part CSV onto the final output with a large buffer.
    Returns approximate number of newline-terminated data rows appended.
    """
    part = Path(part_path)
    if not part.is_file() or part.stat().st_size == 0:
        return 0
    out = Path(output_path)
    rows = 0
    with part.open("rb") as src, out.open("ab", buffering=BUFFER_SIZE) as dst:
        while True:
            chunk = src.read(BUFFER_SIZE)
            if not chunk:
                break
            rows += chunk.count(b"\n")
            dst.write(chunk)
    return rows
