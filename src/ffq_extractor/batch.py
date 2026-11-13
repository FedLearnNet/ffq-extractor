"""High-throughput ZIP batch extraction for 100k+ FFQ workbooks."""

from __future__ import annotations

import os
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .export import append_csv_part, init_output_csv, write_part_csv
from .mapping import default_mapping_path
from .parse import extract_ffq

EXCEL_SUFFIXES = {".xlsx", ".xlsm"}

# Per-process mapping cache filled by pool initializer
_WORKER_MAPPING = None
_WORKER_MAPPING_PATH: Optional[str] = None


@dataclass
class BatchResult:
    files_total: int = 0
    files_ok: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    rows_written: int = 0
    omitted_blank: int = 0
    omitted_never: int = 0
    omitted_na_mapping: int = 0
    omitted_odd_mark: int = 0
    elapsed_seconds: float = 0.0
    failed_members: List[str] = field(default_factory=list)
    output_csv: Optional[Path] = None
    error_log: Optional[Path] = None

    @property
    def ok(self) -> bool:
        return self.files_failed == 0 and self.files_ok > 0


def list_excel_members(zip_path: Union[str, Path]) -> List[str]:
    """Return Excel member names inside a ZIP, skipping junk paths."""
    members: List[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            base = name.rsplit("/", 1)[-1]
            if not base or base.startswith("."):
                continue
            if name.startswith("__MACOSX/") or "/__MACOSX/" in name:
                continue
            suffix = Path(base).suffix.lower()
            if suffix in EXCEL_SUFFIXES:
                members.append(info.filename)
    return members


def _worker_init(mapping_path: str) -> None:
    global _WORKER_MAPPING, _WORKER_MAPPING_PATH
    from .mapping import load_food_mapping

    _WORKER_MAPPING_PATH = mapping_path
    _WORKER_MAPPING = load_food_mapping(mapping_path)


def _process_zip_member(
    zip_path: str,
    member_name: str,
    sheet_name: str,
    strict: bool,
    parts_dir: str,
) -> Tuple[str, bool, Optional[str], Dict[str, int], Optional[str]]:
    """
    Worker entrypoint.

    Returns:
        member_name, ok, part_csv_path|None, counts, error_summary|None
    """
    global _WORKER_MAPPING
    counts = {
        "rows": 0,
        "omitted_blank": 0,
        "omitted_never": 0,
        "omitted_na_mapping": 0,
        "omitted_odd_mark": 0,
    }
    tmp_xlsx: Optional[Path] = None
    part_path: Optional[Path] = None
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Unique safe temp name
            suffix = Path(member_name).suffix or ".xlsx"
            fd, tmp_name = tempfile.mkstemp(prefix="ffq_", suffix=suffix, dir=parts_dir)
            os.close(fd)
            tmp_xlsx = Path(tmp_name)
            with zf.open(member_name, "r") as src, tmp_xlsx.open("wb") as dst:
                shutil_copy = __import__("shutil").copyfileobj
                shutil_copy(src, dst, length=8 * 1024 * 1024)

        result = extract_ffq(
            tmp_xlsx,
            sheet_name=sheet_name,
            strict=strict,
            food_mapping=_WORKER_MAPPING,
            read_only=True,
        )
        counts["omitted_blank"] = result.omitted_blank
        counts["omitted_never"] = result.omitted_never
        counts["omitted_na_mapping"] = result.omitted_na_mapping
        counts["omitted_odd_mark"] = result.omitted_odd_mark

        if result.errors:
            summary = "; ".join(result.errors[:5])
            if len(result.errors) > 5:
                summary += f" (+{len(result.errors) - 5} more)"
            return member_name, False, None, counts, summary

        if not result.rows:
            # Valid empty questionnaire still counts as ok
            return member_name, True, None, counts, None

        safe = member_name.replace("/", "__").replace("\\", "__")
        part_path = Path(parts_dir) / f"{safe}.part.csv"
        write_part_csv(result.rows, part_path)
        counts["rows"] = len(result.rows)
        return member_name, True, str(part_path), counts, None
    except Exception as exc:  # noqa: BLE001 - isolate per-file failures
        return member_name, False, None, counts, f"{type(exc).__name__}: {exc}"
    finally:
        if tmp_xlsx is not None:
            try:
                tmp_xlsx.unlink(missing_ok=True)
            except OSError:
                pass


def process_zip(
    zip_path: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    mapping_path: Optional[Union[str, Path]] = None,
    error_log: Optional[Union[str, Path]] = None,
    sheet_name: str = "Sheet1",
    strict: bool = False,
    workers: Optional[int] = None,
    progress_every: int = 50,
    progress_callback=None,
) -> BatchResult:
    """
    Extract all FFQ Excel members from a ZIP into one Nutrition CSV.

    Designed for 100k+ members: process pool, part CSVs, as-completed merge,
    sidecar error log (bounded memory).
    """
    zip_path = Path(zip_path)
    output_csv = Path(output_csv)
    mapping_path = Path(mapping_path) if mapping_path else default_mapping_path()
    error_log_path = (
        Path(error_log) if error_log else output_csv.with_suffix(output_csv.suffix + ".errors.log")
    )

    members = list_excel_members(zip_path)
    result = BatchResult(
        files_total=len(members),
        output_csv=output_csv,
        error_log=error_log_path,
    )
    if not members:
        error_log_path.write_text("No Excel (.xlsx/.xlsm) members found in archive.\n", encoding="utf-8")
        result.files_failed = 1
        return result

    init_output_csv(output_csv)
    error_log_path.write_text("", encoding="utf-8")

    worker_count = max(1, workers if workers is not None else (os.cpu_count() or 4))
    started = time.perf_counter()
    done = 0

    with tempfile.TemporaryDirectory(prefix="ffq_batch_") as parts_dir:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_worker_init,
            initargs=(str(mapping_path),),
        ) as pool:
            futures = {
                pool.submit(
                    _process_zip_member,
                    str(zip_path),
                    member,
                    sheet_name,
                    strict,
                    parts_dir,
                ): member
                for member in members
            }

            with error_log_path.open("a", encoding="utf-8") as err_handle:
                for fut in as_completed(futures):
                    member, ok, part, counts, err = fut.result()
                    done += 1
                    result.omitted_blank += counts.get("omitted_blank", 0)
                    result.omitted_never += counts.get("omitted_never", 0)
                    result.omitted_na_mapping += counts.get("omitted_na_mapping", 0)
                    result.omitted_odd_mark += counts.get("omitted_odd_mark", 0)

                    if ok:
                        result.files_ok += 1
                        if part:
                            result.rows_written += append_csv_part(part, output_csv)
                            try:
                                Path(part).unlink(missing_ok=True)
                            except OSError:
                                pass
                    else:
                        result.files_failed += 1
                        result.failed_members.append(member)
                        err_handle.write(f"{member}\t{err or 'unknown error'}\n")
                        err_handle.flush()

                    if progress_callback and (
                        done % progress_every == 0 or done == result.files_total
                    ):
                        progress_callback(done, result.files_total, result)

    result.elapsed_seconds = time.perf_counter() - started
    return result


def process_input(
    input_path: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    mapping_path: Optional[Union[str, Path]] = None,
    error_log: Optional[Union[str, Path]] = None,
    sheet_name: str = "Sheet1",
    strict: bool = False,
    workers: Optional[int] = None,
    progress_callback=None,
) -> BatchResult:
    """Dispatch single workbook vs ZIP archive."""
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return process_zip(
            path,
            output_csv,
            mapping_path=mapping_path,
            error_log=error_log,
            sheet_name=sheet_name,
            strict=strict,
            workers=workers,
            progress_callback=progress_callback,
        )

    # Single workbook — fail-fast
    from .export import write_csv
    from .parse import ExtractError

    started = time.perf_counter()
    error_log_path = (
        Path(error_log) if error_log else Path(output_csv).with_suffix(".errors.log")
    )
    batch = BatchResult(
        files_total=1,
        output_csv=Path(output_csv),
        error_log=error_log_path,
    )
    try:
        extracted = extract_ffq(
            path,
            mapping_path=mapping_path,
            sheet_name=sheet_name,
            strict=strict,
            read_only=True,
        )
    except ExtractError as exc:
        error_log_path.write_text(f"{path.name}\t{exc}\n", encoding="utf-8")
        batch.files_failed = 1
        batch.failed_members.append(path.name)
        batch.elapsed_seconds = time.perf_counter() - started
        return batch

    batch.omitted_blank = extracted.omitted_blank
    batch.omitted_never = extracted.omitted_never
    batch.omitted_na_mapping = extracted.omitted_na_mapping
    batch.omitted_odd_mark = extracted.omitted_odd_mark

    if extracted.errors:
        error_log_path.write_text(
            f"{path.name}\t" + "; ".join(extracted.errors) + "\n",
            encoding="utf-8",
        )
        batch.files_failed = 1
        batch.failed_members.append(path.name)
    else:
        write_csv(extracted.rows, output_csv)
        error_log_path.write_text("", encoding="utf-8")
        batch.files_ok = 1
        batch.rows_written = len(extracted.rows)

    batch.elapsed_seconds = time.perf_counter() - started
    return batch
