from dbtsql.sites import discover
from dbtsql.shape import tree
from dbtsql.units import parse


def _mutants(sql):
    return [(site.original, site.mutant, site.category) for site in discover(sql)]


def apply(source, site):
    data = source.encode()
    return (data[: site.start] + site.mutant.encode() + data[site.end :]).decode()


def test_operators_and_null_checks():
    assert _mutants("select a from t where a >= 1 and b is null and c is not null or d <> e") == [
        (">=", ">", "comparison"),
        ("1", "0", "constant"),
        ("and", "or", "logical"),
        ("is", "is not", "null"),
        ("and", "or", "logical"),
        ("is not", "is", "null"),
        ("or", "and", "logical"),
        ("<>", "=", "comparison"),
    ]


def test_star_and_unary_minus_and_between_are_not_mutated():
    assert _mutants("select *, count(*), -a from t where x between 2 and 3") == []


def test_joins_aggregates_order_and_negation():
    assert _mutants(
        "select min(a) from t left join u on a.k = u.k join v on v.k = t.k "
        "where c not in (2) and d in (3) qualify row_number() over (order by e desc) = 1"
    ) == [
        ("min", "max", "aggregate"),
        ("left", "inner", "join"),
        ("=", "!=", "comparison"),
        ("join", "left join", "join"),
        ("=", "!=", "comparison"),
        ("not in", "in", "negation"),
        ("and", "or", "logical"),
        ("in", "not in", "negation"),
        ("desc", "asc", "order"),
        ("=", "!=", "comparison"),
        ("1", "0", "constant"),
    ]


def test_jinja_is_never_mutated_and_offsets_are_bytes():
    source = "-- åäö\n{% if a == 1 %}select{% endif %} {{ x > 1 }} from t where ö = 1"
    found = discover(source)
    assert [(s.original, s.mutant) for s in found] == [("=", "!="), ("1", "0")]
    assert apply(source, found[0]).endswith("where ö != 1")


def test_tree_normalizes_names_but_keeps_calls_and_shape():
    left = parse("select a, coalesce(b, 0) from {{ ref('x') }} where c = 'y'")
    right = parse("select z, coalesce(q, 9) from {{ ref('other') }} where w = 'k'")
    assert tree(left, left.units[0]) == tree(right, right.units[0])
    assert tree(left, left.units[0]) == [
        [["SELECT", "id"], ["COALESCE", ["PAREN", [["id"], ["num"]]]]],
        [["FROM", "jinja"]],
        [["WHERE", "id", "EQ", "str"]],
    ]
