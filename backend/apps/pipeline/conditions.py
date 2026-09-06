"""A sandboxed evaluator for ``pipeline_transition_rules.condition_expr``.

The schema review is blunt about this column: *"stores an expression evaluated
at transition time. Evaluate it in a sandboxed expression parser, never
``eval()``. Restrict write access to this table to a single administrative
role."* Both halves are honoured — this module is the parser, and Appendix B
grants ``transition_rule:edit`` to OWNER and ADMIN only.

The design is an allowlist over the stdlib ``ast`` module, roughly 120 lines
and no new dependency (BACKEND_PLAN.md section 7). Everything not explicitly
permitted raises ``NotImplementedError``, as the prompt directs.

Two properties are worth being explicit about, because they are what make this
safe rather than merely awkward to abuse:

* **No calls at all.** ``ast.Call`` is not in the allowlist, so there is no
  ``__import__``, no ``getattr``, no method invocation, and no way to reach a
  Python object from inside an expression.
* **No attribute traversal.** A dotted name like ``job_card.dispatch_policy``
  is resolved as a *string key* against a flat context dictionary, never with
  ``getattr``. An expression cannot walk from a value to its ``__class__`` and
  out into the interpreter.

The context is built by ``pipeline.services.condition_context`` and is a flat
mapping of scalars. Rule authors see a documented, finite vocabulary.
"""

from __future__ import annotations

import ast
from typing import Any

from apps.core.exceptions import ConfigurationError

#: An expression longer than this is a mistake, not a rule.
MAX_EXPRESSION_LENGTH = 500
#: Guards against a deeply nested literal exhausting the stack.
MAX_DEPTH = 20

_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.List,
    ast.Tuple,
    ast.Set,
)

_COMPARATORS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BINARY_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}


class ConditionError(ConfigurationError):
    """The expression is not something this evaluator will run.

    A ``ConfigurationError`` rather than a user-facing error: a broken
    ``condition_expr`` is bad seed data, and no action the user takes can fix
    it. It surfaces as a 500 so it is noticed, rather than as a 403 that would
    look like an ordinary permission problem.
    """


def _dotted_name(node: ast.AST) -> str | None:
    """Flatten ``a.b.c`` into ``"a.b.c"``, or return None if it is not a plain path."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _check_nodes(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise NotImplementedError(
                f"{type(node).__name__} is not permitted in a transition condition. "
                "Conditions may use names, literals, comparisons, and/or/not, and "
                "simple arithmetic — nothing else."
            )


def _depth(node: ast.AST, level: int = 0) -> int:
    if level > MAX_DEPTH:
        raise ConditionError("Transition condition is nested too deeply.")
    return max((_depth(child, level + 1) for child in ast.iter_child_nodes(node)), default=level)


def evaluate(expression: str, context: dict[str, Any]) -> bool:
    """Evaluate ``expression`` against ``context`` and return a boolean.

    Raises ``NotImplementedError`` for anything outside the allowlist and
    ``ConditionError`` for an expression that is well-formed but cannot be
    resolved — an unknown name, say, which almost always means a rule was
    written against a field that does not exist.
    """
    if expression is None:
        return True
    expression = expression.strip()
    if not expression:
        return True
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ConditionError(
            f"Transition condition is {len(expression)} characters; "
            f"the limit is {MAX_EXPRESSION_LENGTH}."
        )

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"Transition condition is not valid syntax: {exc.msg}") from exc

    _check_nodes(tree)
    _depth(tree)

    return bool(_eval(tree.body, context))


def _eval(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _dotted_name(node)
        if name is None:
            raise NotImplementedError(
                "Only plain names and dotted names are permitted in a condition."
            )
        if name not in ctx:
            raise ConditionError(
                f"Transition condition refers to {name!r}, which is not available. "
                f"Available names: {', '.join(sorted(ctx))}."
            )
        return ctx[name]

    if isinstance(node, ast.BoolOp):
        # Short-circuits, matching Python.
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval(value, ctx)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _eval(value, ctx)
            if result:
                return result
        return result

    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand

    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, ctx)
            func = _COMPARATORS.get(type(op))
            if func is None:  # pragma: no cover — _check_nodes rejects these first
                raise NotImplementedError(f"{type(op).__name__} is not permitted.")
            if not func(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BinOp):
        func = _BINARY_OPS.get(type(node.op))
        if func is None:  # pragma: no cover — _check_nodes rejects these first
            raise NotImplementedError(f"{type(node.op).__name__} is not permitted.")
        try:
            return func(_eval(node.left, ctx), _eval(node.right, ctx))
        except ZeroDivisionError as exc:
            raise ConditionError("Transition condition divides by zero.") from exc

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(element, ctx) for element in node.elts]

    if isinstance(node, ast.Set):
        return {_eval(element, ctx) for element in node.elts}

    raise NotImplementedError(  # pragma: no cover — _check_nodes rejects these first
        f"{type(node).__name__} is not permitted in a transition condition."
    )
