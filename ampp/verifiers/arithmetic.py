"""Bounded arithmetic AST, shared by diagnostic verifiers.

Never pass candidate text to eval, sympify, or a Python code parser that executes
it. Only integer literals, identifiers, +, -, *, and small nonnegative powers
are supported. Unsupported syntax is inconclusive, not a theorem.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Callable


class UnsupportedExpression(ValueError):
    """The statement is outside the supported arithmetic fragment."""


COMPARISONS = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}


def parse_relation(
    statement: str, integer: Callable[[int], Any], symbol: Callable[[str], Any]
) -> tuple[Any, str, Any]:
    """Build arithmetic objects without evaluating any candidate code."""
    if len(statement) > 2000:
        raise UnsupportedExpression("statement too long")
    parts = re.split(r"(<=|>=|!=|==|=|<|>)", statement)
    if len(parts) != 3:
        raise UnsupportedExpression("expected one comparison")

    def expression(text: str) -> Any:
        try:
            tree = ast.parse(text.strip(), mode="eval")
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedExpression("invalid arithmetic") from exc
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise UnsupportedExpression("expression too complex")

        def visit(node: ast.AST) -> Any:
            if isinstance(node, ast.Constant) and type(node.value) is int:
                if abs(node.value) > 10**12:
                    raise UnsupportedExpression("integer too large")
                return integer(node.value)
            if isinstance(node, ast.Name) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", node.id):
                return symbol(node.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Pow):
                    if (
                        not isinstance(node.right, ast.Constant)
                        or type(node.right.value) is not int
                        or not 0 <= node.right.value <= 8
                    ):
                        raise UnsupportedExpression("power must be an integer from 0 to 8")
                    # Repeated multiplication keeps Z3 expressions in integer arithmetic.
                    base = visit(node.left)
                    value = integer(1)
                    for _ in range(node.right.value):
                        value = value * base
                    return value
                ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}
                op = ops.get(type(node.op))
                if op is not None:
                    return op(visit(node.left), visit(node.right))
            raise UnsupportedExpression("unsupported arithmetic syntax")

        return visit(tree.body)

    return expression(parts[0]), parts[1], expression(parts[2])
