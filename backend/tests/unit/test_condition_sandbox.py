"""The condition evaluator's allowlist.

``condition_expr`` is written by an administrator and evaluated at transition
time. The schema review names it as a remaining risk and says: sandboxed
parser, never ``eval()``. These tests are the evidence that the sandbox holds —
the escape attempts matter more than the happy path.
"""

import pytest

from apps.pipeline.conditions import ConditionError, evaluate

CONTEXT = {
    "quantity": 5,
    "is_manufactured": True,
    "dispatch_policy": "partial_allowed",
    "lifecycle_status": "open",
    "stage_code": "ENQUIRY",
    "job_card.dispatch_policy": "partial_allowed",
}


# --- what it is meant to do ------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("quantity > 3", True),
        ("quantity > 10", False),
        ("quantity >= 5 and is_manufactured", True),
        ("not is_manufactured", False),
        ("dispatch_policy == 'partial_allowed'", True),
        ("dispatch_policy != 'complete_only'", True),
        ("lifecycle_status in ['open', 'quoted']", True),
        ("lifecycle_status not in ['won', 'lost']", True),
        ("quantity * 2 == 10", True),
        ("quantity + 1 > 5", True),
        ("(quantity > 3) or (quantity < 1)", True),
        ("1 < quantity < 10", True),
        ("job_card.dispatch_policy == 'partial_allowed'", True),
        ("-quantity < 0", True),
        ("quantity % 2 == 1", True),
    ],
)
def test_permitted_expressions(expression, expected):
    assert evaluate(expression, CONTEXT) is expected


def test_an_empty_condition_is_treated_as_no_condition():
    assert evaluate("", CONTEXT) is True
    assert evaluate("   ", CONTEXT) is True
    assert evaluate(None, CONTEXT) is True


def test_and_short_circuits():
    """`unknown_name` would raise if it were evaluated."""
    assert evaluate("False and unknown_name", CONTEXT) is False


def test_or_short_circuits():
    assert evaluate("True or unknown_name", CONTEXT) is True


# --- what it refuses --------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "quantity.__class__",
        "().__class__.__bases__",
        "[].__class__.__mro__[1].__subclasses__()",
        "eval('1+1')",
        "exec('x=1')",
        "globals()",
        "locals()",
        "len('abc')",
        "quantity.bit_length()",
        "lambda: 1",
        "[x for x in range(10)]",
        "{'a': 1}['a']",
        "quantity if True else 0",
        "quantity := 5",
    ],
)
def test_escape_attempts_are_refused(expression):
    """Anything outside the allowlist raises, and never evaluates.

    Note that several of these are refused at parse time and the rest by the
    node allowlist; either way nothing is executed.
    """
    with pytest.raises((NotImplementedError, ConditionError, SyntaxError)):
        evaluate(expression, CONTEXT)


def test_attribute_access_never_reaches_a_python_object():
    """A dotted name is a *string key* into the context, not getattr. So even
    an attribute that exists on the underlying value is unreachable."""
    with pytest.raises(ConditionError, match="not available"):
        evaluate("quantity.numerator", CONTEXT)


def test_an_unknown_name_is_a_configuration_error_naming_what_is_available():
    with pytest.raises(ConditionError) as caught:
        evaluate("salary > 100", CONTEXT)

    message = str(caught.value)
    assert "salary" in message
    assert "quantity" in message, "the error should list the available names"


def test_invalid_syntax_is_a_configuration_error_not_a_crash():
    with pytest.raises(ConditionError, match="not valid syntax"):
        evaluate("quantity >", CONTEXT)


def test_an_over_long_expression_is_refused():
    with pytest.raises(ConditionError, match="the limit is"):
        evaluate("quantity > 1 and " * 200 + "True", CONTEXT)


def test_division_by_zero_is_a_configuration_error():
    with pytest.raises(ConditionError, match="divides by zero"):
        evaluate("quantity / 0 > 1", CONTEXT)


def test_deeply_nested_expressions_are_refused():
    """Nesting has to come from operators, not parentheses — Python's parser
    discards redundant parentheses, so `((((True))))` is one AST node."""
    with pytest.raises(ConditionError, match="nested too deeply"):
        evaluate("not " * 30 + "True", CONTEXT)


def test_redundant_parentheses_are_not_mistaken_for_depth():
    assert evaluate("(" * 30 + "True" + ")" * 30, CONTEXT) is True


def test_the_result_is_always_a_boolean():
    """A rule returning a truthy string should read as satisfied, not leak the
    string back to the caller."""
    assert evaluate("'nonempty'", CONTEXT) is True
    assert evaluate("0", CONTEXT) is False
