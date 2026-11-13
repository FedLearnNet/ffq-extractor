from pathlib import Path
from typing import Optional

from pydantic.dataclasses import dataclass
from pyfedappwrap.learning.run_runfig import AppConfig, AppInputConfig, AppOutputConfig


@dataclass
class MyAppConfig(AppConfig):
    workers: int = 4
    strict: bool = False
    sheet: str = "Sheet1"


@dataclass
class MyAppInputConfig(AppInputConfig):
    ffq_archive: Path


@dataclass
class MyAppOutputConfig(AppOutputConfig):
    nutrition_csv: Optional[Path] = None
