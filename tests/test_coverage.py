import json
from pathlib import Path

from dbtsql import coverage


def _project(tmp_path: Path) -> Path:
    (tmp_path / "dbt_project.yml").write_text("name: demo\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "macros").mkdir()
    (tmp_path / "models" / "_unit.yml").write_text("unit_tests:\n  - name: t\n    model: tested\n")
    (tmp_path / "models" / "tested.sql").write_text(
        "with a as (\n  select {{ outer_macro() }} from x\n)\n\nselect * from a\n"
    )
    (tmp_path / "models" / "untested.sql").write_text("select {{ lonely() }} from y\n")
    (tmp_path / "macros" / "m.sql").write_text(
        "{% macro outer_macro() %}\n{{ inner_macro() }}\n{% endmacro %}\n"
        "{% macro inner_macro() %}\n1\n{% endmacro %}\n"
        "{% macro lonely() %}\n2\n{% endmacro %}\n"
    )
    return tmp_path


def _fake_dbt(project: Path):
    calls = []

    def run(command, cwd):
        calls.append((command, cwd))
        (project / "target").mkdir(exist_ok=True)
        results = {
            "results": [
                {"unique_id": "unit_test.demo.tested.t", "status": "pass"},
                {"unique_id": "unit_test.demo.untested.u", "status": "fail"},
            ]
        }
        (project / "target" / "run_results.json").write_text(json.dumps(results))
        return 0

    return run, calls


def _hits(text: str, name: str) -> list[str]:
    record = text.split(f"SF:")[1:]
    for chunk in record:
        if chunk.splitlines()[0].endswith(name):
            return [line for line in chunk.splitlines() if line.startswith("DA:")]
    raise AssertionError(name)


def test_passing_unit_tests_cover_their_model_and_the_macros_it_reaches(tmp_path):
    project = _project(tmp_path)
    run, calls = _fake_dbt(project)
    files = sorted(project.rglob("*.sql"))
    report = project / "target" / "coverage" / "sql" / "lcov.info"
    coverage.write(files, report, run)

    assert [command[:4] for command, _cwd in calls] == [["dbt", "test", "--select", "test_type:unit"]]
    text = report.read_text()
    assert _hits(text, "tested.sql") == ["DA:1,1", "DA:2,1", "DA:3,1", "DA:5,1"]
    assert _hits(text, "untested.sql") == ["DA:1,0"]
    assert _hits(text, "m.sql") == [
        "DA:1,1", "DA:2,1", "DA:3,1",
        "DA:4,1", "DA:5,1", "DA:6,1",
        "DA:7,0", "DA:8,0", "DA:9,0",
    ]


def test_project_without_unit_tests_runs_no_dbt(tmp_path):
    project = _project(tmp_path)
    (project / "models" / "_unit.yml").unlink()
    run, calls = _fake_dbt(project)
    coverage.write(sorted(project.rglob("*.sql")), project / "lcov.info", run)
    assert calls == []
    assert "DA:1,1" not in (project / "lcov.info").read_text()
