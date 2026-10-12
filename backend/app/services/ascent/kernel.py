"""Capability-free interpreter for the first source-evolution component.

Candidate text is parsed, never imported, compiled, eval'd or exec'd. The tiny
expression language has no filesystem, network, environment, process, object
attribute or mutation operations. Limits bound work independently of the host
Python sandbox. Expanding this language requires a separate security review.
"""

from __future__ import annotations

import ast
import hashlib
import math
import operator


_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub,
              ast.Mult: operator.mul, ast.Div: operator.truediv}
IDENTITY_SOURCE = "def calibrate(p):\n    return p\n"
KERNEL_VERSION = "ascent-arithmetic-v1"


class ArithmeticKernel:
    def __init__(self, source: str):
        if not isinstance(source, str) or len(source.encode()) > 2048:
            raise ValueError("SOURCE_SIZE_LIMIT")
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError) as exc:
            raise ValueError("INVALID_SOURCE") from exc
        if len(list(ast.walk(tree))) > 128 or len(tree.body) != 1:
            raise ValueError("AST_LIMIT")
        function = tree.body[0]
        if not isinstance(function, ast.FunctionDef) or function.name != "calibrate":
            raise ValueError("ONLY_CALIBRATE_ALLOWED")
        args = function.args
        if (function.decorator_list or function.returns or args.posonlyargs or
                args.kwonlyargs or args.defaults or args.kw_defaults or args.vararg or
                args.kwarg or len(args.args) != 1 or args.args[0].arg != "p" or
                args.args[0].annotation or len(function.body) != 1 or
                not isinstance(function.body[0], ast.Return)):
            raise ValueError("INVALID_FUNCTION_CONTRACT")
        self._expression = function.body[0].value
        self._validate(self._expression, depth=0)
        self.source = source
        self.sha256 = hashlib.sha256(source.encode()).hexdigest()

    def _validate(self, node: ast.AST, *, depth: int) -> None:
        if depth > 16:
            raise ValueError("EXPRESSION_DEPTH_LIMIT")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(node.value) or abs(node.value) > 100:
                raise ValueError("INVALID_CONSTANT")
        elif isinstance(node, ast.Name) and node.id == "p":
            return
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            self._validate(node.left, depth=depth + 1)
            self._validate(node.right, depth=depth + 1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self._validate(node.operand, depth=depth + 1)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
              node.func.id in ("min", "max") and not node.keywords and len(node.args) == 2):
            for argument in node.args:
                self._validate(argument, depth=depth + 1)
        else:
            raise ValueError("FORBIDDEN_SYNTAX")

    def predict(self, p: float) -> float:
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("INVALID_INPUT_PROBABILITY")
        try:
            value = float(self._evaluate(self._expression, float(p)))
        except (ArithmeticError, OverflowError) as exc:
            raise ValueError("INVALID_ARITHMETIC") from exc
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("INVALID_OUTPUT_PROBABILITY")
        return value

    def _evaluate(self, node: ast.AST, p: float) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return p
        if isinstance(node, ast.BinOp):
            return _OPERATORS[type(node.op)](self._evaluate(node.left, p), self._evaluate(node.right, p))
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate(node.operand, p)
            return -value if isinstance(node.op, ast.USub) else value
        values = [self._evaluate(arg, p) for arg in node.args]
        return min(values) if node.func.id == "min" else max(values)


def generate_candidates(*, prior: float, limit: int = 4) -> tuple[str, ...]:
    if not math.isfinite(prior) or not 0 <= prior <= 1 or not 1 <= limit <= 4:
        raise ValueError("INVALID_GENERATION_BUDGET_OR_PRIOR")
    return tuple(
        f"def calibrate(p):\n    return min(1, max(0, {slope:g} * p + {(1 - slope) * prior:.12g}))\n"
        for slope in (0.0, 0.25, 0.5, 0.75)[:limit]
    )
