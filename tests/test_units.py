from dbtsql.jinja import mask
from dbtsql.units import units

MODEL = """{{ config(materialized='table') }}

with source as (

    select * from {{ ref('raw_orders') }}
    where amount between 1 and 10

)

, final as (
    select
        id,
        case when status = 'x' then 1 when status = 'y' then 2 else 3 end as code,
        coalesce(a, b) as c
    from source
    {% if is_incremental() and true %}
    where updated_at > (select max(updated_at) from {{ this }})
    {% endif %}
)

select * from final
"""


def test_mask_keeps_offsets_and_lines():
    masked = mask(MODEL)
    assert len(masked.text) == len(MODEL)
    assert masked.text.count("\n") == MODEL.count("\n")
    assert "from jjjjjjjjjjjjjjjjjjjj" in masked.text
    assert "{%" not in masked.text


def test_model_units_are_ctes_and_main():
    found = units(MODEL)
    assert [(u.name, u.kind) for u in found] == [("source", "cte"), ("final", "cte"), ("main", "main")]
    source, final, main = found
    assert (source.start_line, source.end_line) == (3, 8)
    assert (final.start_line, final.end_line) == (10, 19)
    assert (main.start_line, main.end_line) == (21, 21)


def test_complexity_counts_sql_and_jinja_decisions():
    source, final, main = units(MODEL)
    # where; the between-and is not a decision
    assert source.complexity == 2
    # 2 when + coalesce + {% if %} + jinja `and` + where
    assert final.complexity == 7
    assert main.complexity == 1


def test_model_without_ctes_is_one_main():
    found = units("{{ config(x=1) }}\nselect a from t where a = 1 or b = 2\n")
    assert [(u.name, u.complexity, u.start_line) for u in found] == [("main", 3, 2)]


def test_macro_file_has_one_unit_per_macro():
    source = """{% macro first(x) %}
  {% if x %}{{ x }}{% else %}null{% endif %}
{% endmacro %}

{%- macro second() -%}
  select 1
{%- endmacro %}
"""
    found = units(source)
    assert [(u.name, u.kind, u.start_line, u.end_line, u.complexity) for u in found] == [
        ("first", "macro", 1, 3, 2),
        ("second", "macro", 5, 7, 1),
    ]


def test_unreadable_sql_is_one_unit():
    found = units("select 'unterminated from t\n")
    assert [(u.name, u.start_line) for u in found] == [("main", 1)]


def test_mask_skips_quoted_closers_inside_a_tag():
    source = "{{ config(pre_hook=['{{ m() }}']) }}\nselect 1"
    masked = mask(source)
    assert masked.text.endswith("\nselect 1")
    assert [tag.kind for tag in masked.tags] == ["expr"]


def test_a_cte_that_only_selects_columns_from_a_ref_is_an_import():
    found = units(
        "with a as (select x, y as z from {{ ref('r') }}),\n"
        "b as (select * from {{ source('s', 't') }}),\n"
        "c as (select x from {{ ref('r') }} where x > 1),\n"
        "d as (select x from a)\n"
        "select * from d"
    )
    assert [(u.name, u.kind) for u in found] == [
        ("a", "import"), ("b", "import"), ("c", "cte"), ("d", "cte"), ("main", "main")
    ]
