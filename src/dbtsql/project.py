"""Where a SQL file's dbt project is, and the dbt command that tests it."""

from __future__ import annotations

import os
from pathlib import Path

from dbtsql.units import namespace


def nearest(start: Path, marker: str) -> Path | None:
    current = start if start.is_dir() else start.parent
    for directory in [current, *current.parents]:
        if (directory / marker).is_file():
            return directory
    return None


def project_dir(source: Path) -> Path | None:
    return nearest(source.resolve(), "dbt_project.yml")


def profiles_dir(project: Path) -> Path | None:
    """The nearest profiles.yml at or above the project, else dbt's own default."""

    found = nearest(project.resolve(), "profiles.yml")
    if found is not None:
        return found
    configured = os.environ.get("DBT_PROFILES_DIR")
    return Path(configured) if configured else None


def is_macro(source: Path, project: Path) -> bool:
    relative = source.resolve().relative_to(project.resolve())
    return relative.parts[:1] == ("macros",)


def selector(source: Path, project: Path) -> str:
    """A model's own unit tests. A macro can reach any model, so all of them."""

    if is_macro(source, project):
        return "test_type:unit"
    return f"{namespace(source.name)},test_type:unit"


def test_command(project: Path, select: str) -> list[str]:
    command = ["dbt", "test", "--select", select]
    profiles = profiles_dir(project)
    if profiles is not None:
        command.extend(["--profiles-dir", str(profiles)])
    return command
