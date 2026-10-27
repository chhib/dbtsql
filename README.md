# dbtsql

dbt SQL with Jinja for uncle Bob's `crapper`, `dryer` and `mutator`
(`~/code/unclebob/*`, branch `sql-dbt`). The tools' `sql` plugins are thin;
the decisions live here.

| Module | Decides |
|---|---|
| `jinja` | Masks `{{ }}`, `{% %}` and `{# #}` at the same offsets so SQL tools read the file |
| `units` | Units: each top-level CTE, the final select (`main`), each macro. Cyclomatic complexity |
| `shape` | The normalized tree dryer compares. Import CTEs are skipped |
| `sites` | Mutation sites outside Jinja |
| `coverage` | LCOV from passing dbt unit tests |
| `project` | dbt project, `profiles.yml`, and the `dbt test` command per file |

## Rules

- **Complexity:** 1 + `WHEN`, `AND`/`OR` (not BETWEEN's), `WHERE`, `HAVING`,
  `QUALIFY`, `IFF`/`COALESCE`/`NVL`/`NVL2`/`IFNULL`/`DECODE`, plus Jinja
  `if`/`elif`/`for`, inline `if`, and `and`/`or` inside tags.
- **Coverage:** dbt reports no line coverage. A model is 100% when one of its
  unit tests passes, otherwise 0%. A macro is covered when a covered model
  reaches it.
- **Mutants:** each one runs `dbt test --select <model>,test_type:unit`
  (every unit test for a macro) against the dev target in a copy of the dbt
  project.

## Install into the tools

```sh
for d in crapper dryer mutator; do
  uv pip install --python ~/code/unclebob/$d/.venv/bin/python -e ~/code/ub-codes
done
```

## Use

Run from the dbt project or the repo above it. Coverage and mutator talk to
Snowflake through `profiles.yml` (about 10 s per dbt call).

```sh
crapper                       # runs the unit tests once
dryer
mutator --max-workers 4 models/silver/x.sql
```

`uv run pytest` runs this package's tests.
