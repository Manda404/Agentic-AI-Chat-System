"""Local arithmetic calculator without eval or arbitrary code execution."""

import ast
import math
import operator
import re
from typing import Callable

from app.models.chat_models import ToolResult


class CalculatorTool:
    """Evaluate a bounded subset of Python arithmetic."""

    name = "calculator"
    _MAX_EXPRESSION_CHARS = 200
    _MAX_AST_NODES = 50
    _MAX_ABS_VALUE = 1e100
    _MAX_ABS_EXPONENT = 12
    _BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def run(self, request: str) -> ToolResult:
        """Extract and safely evaluate an arithmetic expression."""
        try:
            expression = self._extract_expression(request)
            value = self._evaluate(expression)
            rendered = str(int(value)) if float(value).is_integer() else f"{value:.12g}"
            return ToolResult(
                tool=self.name,
                output=f"{expression} = {rendered}",
                metadata={"expression": expression, "value": value},
            )
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            return ToolResult(
                tool=self.name,
                output=f"Calculation failed: {exc}",
                success=False,
                metadata={"reason": type(exc).__name__},
            )

    def _extract_expression(self, request: str) -> str:
        normalized = request.lower().replace("^", "**")
        normalized = re.sub(r"(\d+(?:[.,]\d+)?)\s*%\s+(?:of|de)\s+(\d+(?:[.,]\d+)?)", r"(\1 / 100) * \2", normalized)
        candidates = re.findall(r"[-+*/%().\d,\s]+", normalized)
        candidates = [candidate.strip().replace(",", ".") for candidate in candidates]
        candidates = [candidate for candidate in candidates if re.search(r"\d", candidate)]
        if not candidates:
            raise ValueError("no arithmetic expression recognized")
        expression = max(candidates, key=len).strip()
        if len(expression) > self._MAX_EXPRESSION_CHARS:
            raise ValueError("expression too long")
        if not re.search(r"[+*/%-]", expression):
            raise ValueError("an arithmetic operator is required")
        return expression

    def _evaluate(self, expression: str) -> float:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > self._MAX_AST_NODES:
            raise ValueError("expression too complex")
        value = float(self._visit(tree.body))
        if not math.isfinite(value) or abs(value) > self._MAX_ABS_VALUE:
            raise ValueError("result out of bounds")
        return value

    def _visit(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            value = float(node.value)
            if not math.isfinite(value) or abs(value) > self._MAX_ABS_VALUE:
                raise ValueError("number out of bounds")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY_OPERATORS:
            return self._UNARY_OPERATORS[type(node.op)](self._visit(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY_OPERATORS:
            left = self._visit(node.left)
            right = self._visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > self._MAX_ABS_EXPONENT:
                raise ValueError("exponent out of bounds")
            return self._BINARY_OPERATORS[type(node.op)](left, right)
        raise ValueError("operation not allowed")
