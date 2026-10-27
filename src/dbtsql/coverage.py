"""SQL coverage as LCOV, from the dbt unit tests that pass.

dbt reports no line coverage, so a model counts as covered when at least one
of its unit tests passes, and every line of its units is hit. A macro counts
as covered when a covered model calls it, directly or through another macro.
A model without a passing unit test, and a macro nothing covered calls,
scores 0%.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dbtsql.project import is_macro, project_dir, test_command
from dbtsql.units import Parsed, namespace, parse

_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

Run = Callable[[list[str], Path], int]


def _run(command: list[str], cwd: Path) -> int:
    print("+ " + " ".join(command), file=sys.stderr)
    return subprocess.run(command, cwd=cwd).returncode


def _has_unit_tests(project: Path) -> bool:
    for path in (project / "models").rglob("*.y*ml"):
        if "unit_tests:" in path.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def passing_models(project: Path) -> set[str]:
    """Models with a passing unit test in the last run_results.json."""

    results = project / "target" / "run_results.json"
    if not results.is_file():
        return set()
    found: set[str] = set()
    for result in json.loads(results.read_text(encoding="utf-8")).get("results", []):
        parts = str(result.get("unique_id", "")).split(".")
        if parts[0] == "unit_test" and len(parts) >= 4 and result.get("status") == "pass":
            found.add(parts[2])
    return found


def _calls(parsed: Parsed, start: int, end: int) -> set[str]:
    called: set[str] = set()
    for tag in parsed.masked.tags:
        if start <= tag.start < end:
            called.update(_CALL.findall(tag.body))
    return called


def covered_macros(models: list[Parsed], macros: list[Parsed]) -> set[str]:
    bodies = {unit.name: (parsed, unit) for parsed in macros for unit in parsed.units}
    pending: set[str] = set()
    for parsed in models:
        pending |= _calls(parsed, 0, len(parsed.source)) & bodies.keys()
    covered: set[str] = set()
    while pending:
        name = pending.pop()
        covered.add(name)
        parsed, unit = bodies[name]
        pending |= (_calls(parsed, unit.start, unit.end) & bodies.keys()) - covered
    return covered


def _record(path: Path, parsed: Parsed, hit: Callable[[str], bool]) -> str:
    lines = parsed.source.splitlines()
    rows = [f"SF:{path.resolve().as_posix()}"]
    for unit in parsed.units:
        count = 1 if hit(unit.name) else 0
        for number in range(unit.start_line, unit.end_line + 1):
            if number <= len(lines) and lines[number - 1].strip():
                rows.append(f"DA:{number},{count}")
    rows.append("end_of_record")
    return "\n".join(rows) + "\n"


def lcov(files: list[Path], passing: dict[Path, set[str]]) -> str:
    """LCOV for `files`, given the models with passing unit tests per project."""

    models: list[tuple[Path, Parsed, Path]] = []
    macros: list[tuple[Path, Parsed]] = []
    for path in files:
        project = project_dir(path)
        if project is None:
            continue
        parsed = parse(path.read_text(encoding="utf-8", errors="replace"))
        if is_macro(path, project):
            macros.append((path, parsed))
        else:
            models.append((path, parsed, project))
    covered = [
        parsed for path, parsed, project in models if namespace(path.name) in passing.get(project, set())
    ]
    reached = covered_macros(covered, [parsed for _path, parsed in macros])
    text = []
    for path, parsed, project in models:
        tested = namespace(path.name) in passing.get(project, set())
        text.append(_record(path, parsed, lambda _name, tested=tested: tested))
    for path, parsed in macros:
        text.append(_record(path, parsed, lambda name: name in reached))
    return "".join(text)


def write(files: list[Path], report: Path, run: Run = _run) -> None:
    """Run each project's unit tests once, then write LCOV for `files`."""

    projects = sorted({project for path in files if (project := project_dir(path)) is not None})
    passing: dict[Path, set[str]] = {}
    for project in projects:
        if not _has_unit_tests(project):
            continue
        code = run(test_command(project, "test_type:unit"), project)
        if code != 0:
            print(f"dbt unit tests exited {code} in {project}; failing tests count as uncovered.", file=sys.stderr)
        passing[project] = passing_models(project)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(lcov(files, passing), encoding="utf-8")
