"""Compile script control flow once; execute ordinary commands through a callback."""
from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass

from .modbus import DecodedFrame, decode_response
from .runtime_text import tr


class ScriptError(ValueError):
    def __init__(self, key: str, **values: object):
        self.key = key
        self.values = values
        self.line = 1
        super().__init__(key)

    def localized(self, language: str, source: str) -> str:
        return tr(language, "script_error", source=source, line=self.line,
                  reason=tr(language, self.key, **self.values))


@dataclass(frozen=True)
class LastResponse:
    raw: bytes
    decoded: DecodedFrame

    @classmethod
    def from_rx(cls, rx: bytes) -> LastResponse:
        return cls(rx, decode_response(rx))

    def get(self, name: str, index: int | None = None) -> int | bool:
        field = f"last.{name}" if index is None else f"last.{name}[{index}]"
        if name in {"reg", "byte"}:
            values = self.decoded.registers if name == "reg" else self.raw
            if index is None or not 0 <= index < len(values):
                raise ScriptError("script_unavailable", field=field)
            return values[index]
        values = {"timeout": not self.raw, "rx_len": len(self.raw),
                  "address": self.decoded.slave,
                  "function": self.raw[1] if len(self.raw) > 1 else None,
                  "exception": self.decoded.exception_code or 0}
        value = values[name]
        if value is None:
            raise ScriptError("script_unavailable", field=field)
        return value


BIT_OPS = {ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
           ast.LShift: operator.lshift, ast.RShift: operator.rshift}
COMPARE_OPS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
               ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
SCALARS = {"timeout", "rx_len", "address", "function", "exception"}


def _last_attribute(node: ast.AST, names: set[str]) -> bool:
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "last" and node.attr in names)


def _validate(node: ast.AST) -> None:
    children: list[ast.AST]
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return
    if isinstance(node, ast.Name) and node.id in {"true", "false"}:
        return
    if _last_attribute(node, SCALARS):
        return
    if isinstance(node, ast.Subscript) and _last_attribute(node.value, {"reg", "byte"}):
        if isinstance(node.slice, ast.Constant) and type(node.slice.value) is int and node.slice.value >= 0:
            return
    elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        children = node.values
        for child in children:
            _validate(child)
        return
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        _validate(node.operand)
        return
    elif isinstance(node, ast.BinOp) and type(node.op) in BIT_OPS:
        _validate(node.left)
        _validate(node.right)
        return
    elif isinstance(node, ast.Compare) and all(type(op) in COMPARE_OPS for op in node.ops):
        for child in [node.left, *node.comparators]:
            _validate(child)
        return
    raise ScriptError("script_invalid_expression")


def parse_expression(text: str) -> ast.AST:
    try:
        node = ast.parse(text, mode="eval").body
        _validate(node)
        return node
    except (SyntaxError, RecursionError, ValueError) as exc:
        if isinstance(exc, ScriptError):
            raise
        raise ScriptError("script_invalid_expression") from None


def evaluate(node: ast.AST, last: LastResponse | None) -> int | bool:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return node.id == "true"
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        if last is None:
            raise ScriptError("script_no_response")
        if isinstance(node, ast.Subscript):
            return last.get(node.value.attr, node.slice.value)
        return last.get(node.attr)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(evaluate(value, last) for value in node.values)
        return any(evaluate(value, last) for value in node.values)
    if isinstance(node, ast.UnaryOp):
        return not evaluate(node.operand, last)
    if isinstance(node, ast.BinOp):
        left, right = evaluate(node.left, last), evaluate(node.right, last)
        # Bound integer growth from untrusted expressions, never loop iterations.
        if isinstance(node.op, (ast.LShift, ast.RShift)) and not 0 <= right <= 4096:
            raise ScriptError("script_shift_range")
        return BIT_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Compare):
        left = evaluate(node.left, last)
        for op, value in zip(node.ops, node.comparators):
            right = evaluate(value, last)
            if not COMPARE_OPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ScriptError("script_invalid_expression")


@dataclass
class Instruction:
    line: int
    text: str
    kind: str
    target: int = 0
    expression: ast.AST | None = None


@dataclass
class ScriptProgram:
    instructions: list[Instruction]
    labels: dict[str, int]


def compile_script(lines: list[str]) -> ScriptProgram:
    instructions: list[Instruction] = []
    labels: dict[str, int] = {}
    stack: list[tuple[int, int | None]] = []
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split(maxsplit=1)
        word = parts[0].lower()
        arg = parts[1] if len(parts) == 2 else ""
        kind = word if word in {"label", "goto", "if", "else"} else "command"
        if word == "end" and arg.lower().split()[:1] == ["if"]:
            kind = "end if"
        item = Instruction(number, text, kind)
        index = len(instructions)
        try:
            if kind in {"label", "goto"}:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", arg):
                    raise ScriptError("script_invalid_label", name=arg)
                if kind == "label":
                    if arg in labels:
                        raise ScriptError("script_duplicate_label", name=arg)
                    labels[arg] = index + 1
            elif kind == "if":
                item.expression = parse_expression(arg)
                stack.append((index, None))
            elif kind == "else":
                if arg or not stack:
                    raise ScriptError("script_unmatched_else")
                start, alternate = stack[-1]
                if alternate is not None:
                    raise ScriptError("script_duplicate_else")
                instructions[start].target = index + 1
                stack[-1] = (start, index)
            elif kind == "end if":
                if arg.lower() != "if" or not stack:
                    raise ScriptError("script_unmatched_end_if")
                start, alternate = stack.pop()
                instructions[start if alternate is None else alternate].target = index + 1
        except ScriptError as exc:
            exc.line = number
            raise
        instructions.append(item)
    if stack:
        error = ScriptError("script_missing_end_if")
        error.line = instructions[stack[-1][0]].line
        raise error
    for item in instructions:
        if item.kind == "goto":
            name = item.text.split(maxsplit=1)[1]
            if name not in labels:
                error = ScriptError("script_unknown_label", name=name)
                error.line = item.line
                raise error
            item.target = labels[name]
    return ScriptProgram(instructions, labels)


def run_program(program: ScriptProgram, execute: Callable[[Instruction], bool],
                last_response: Callable[[], LastResponse | None],
                between_commands: Callable[[], None]) -> bool:
    pc = 0
    previous_command = False
    while pc < len(program.instructions):
        item = program.instructions[pc]
        try:
            if item.kind in {"goto", "else"}:
                pc = item.target
                continue
            if item.kind == "if":
                assert item.expression is not None
                if not evaluate(item.expression, last_response()):
                    pc = item.target
                    continue
            elif item.kind == "command":
                if previous_command:
                    between_commands()
                if execute(item):
                    return True
                previous_command = True
        except ScriptError as exc:
            exc.line = item.line
            raise
        pc += 1
    return False
