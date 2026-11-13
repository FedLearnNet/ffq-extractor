"""CLI: ffq-extract input.xlsx|patients.zip -o out.csv"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .batch import process_input
from .mapping import default_mapping_path


def run(
    workbook: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to a filled FFQ .xlsx or a .zip of many FFQ workbooks",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output Nutrition CSV path",
    ),
    mapping: Optional[Path] = typer.Option(
        None,
        "--mapping",
        "-m",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Mapping workbook (defaults to vendored file)",
    ),
    sheet: str = typer.Option(
        "Sheet1",
        "--sheet",
        help="Worksheet name containing the FFQ matrix",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warn-level anomalies (odd marks, NA-mapped items) as errors",
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        "-j",
        min=1,
        help="Process-pool size for ZIP batch (default: CPU count)",
    ),
    error_log: Optional[Path] = typer.Option(
        None,
        "--error-log",
        help="Sidecar failure log (default: <output>.errors.log)",
    ),
) -> None:
    """Extract FFQ Excel sheets (or a ZIP of them) into Nutrition CSV rows."""

    def _progress(done: int, total: int, batch) -> None:
        typer.echo(
            f"Progress {done}/{total} ok={batch.files_ok} "
            f"failed={batch.files_failed} rows={batch.rows_written}",
            err=True,
        )

    result = process_input(
        workbook,
        output,
        mapping_path=mapping or default_mapping_path(),
        error_log=error_log,
        sheet_name=sheet,
        strict=strict,
        workers=workers,
        progress_callback=_progress if workbook.suffix.lower() == ".zip" else None,
    )

    rate = (
        result.rows_written / result.elapsed_seconds if result.elapsed_seconds else 0.0
    )
    typer.echo(
        "Summary: "
        f"files_total={result.files_total} "
        f"files_ok={result.files_ok} "
        f"files_failed={result.files_failed} "
        f"rows_written={result.rows_written} "
        f"omitted_blank={result.omitted_blank} "
        f"omitted_never={result.omitted_never} "
        f"omitted_na_mapping={result.omitted_na_mapping} "
        f"omitted_odd_mark={result.omitted_odd_mark} "
        f"elapsed={result.elapsed_seconds:.2f}s "
        f"(~{rate:.0f} rows/s)"
    )
    if result.error_log:
        typer.echo(f"Error log: {result.error_log}", err=True)

    if result.files_failed:
        typer.secho(
            f"Completed with {result.files_failed} failed file(s).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if result.files_ok == 0:
        typer.secho("No files extracted successfully.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho(f"Wrote {result.output_csv}", fg=typer.colors.GREEN)


def app() -> None:
    typer.run(run)


if __name__ == "__main__":
    app()
