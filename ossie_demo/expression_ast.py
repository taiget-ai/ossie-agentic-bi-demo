"""Restricted aggregate-expression parser: explicit AST, never eval or raw SQL.

Supported: SUM/COUNT/AVG (with COUNT DISTINCT), numeric constants, column refs,
parentheses, + - * / and unary minus. Every referenced column must occur under
an aggregation. Unknown SQL functions, comments and SQL statements are rejected.
"""
import re
from dataclasses import dataclass

from .catalog_errors import SemanticError


@dataclass(frozen=True)
class Column:
    dataset: str
    name: str


@dataclass(frozen=True)
class Number:
    value: str


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Aggregate:
    function: str
    argument: object
    distinct: bool = False


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([a-zA-Z_][a-zA-Z_0-9]*)|([.,()+*/-]))")


def tokenize(source: str) -> list[str]:
    tokens = []
    pos = 0
    while pos < len(source):
        match = TOKEN.match(source, pos)
        if not match:
            raise SemanticError(f"unsupported metric expression near {source[pos:pos + 24]!r}")
        tokens.append(next(x for x in match.groups() if x is not None))
        pos = match.end()
    return tokens


class Parser:
    def __init__(self, source):
        self.tokens = tokenize(source)
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected=None):
        value = self.peek()
        if value is None or (expected is not None and value.upper() != expected.upper()):
            raise SemanticError(f"expected {expected or 'expression'}, received {value!r}")
        self.pos += 1
        return value

    def parse(self):
        node = self.sum_expr(False)
        if self.peek() is not None:
            raise SemanticError(f"unexpected metric expression token: {self.peek()}")
        if not contains_aggregate(node):
            raise SemanticError("metric expression requires an aggregate")
        return node

    def sum_expr(self, inside_aggregate):
        node = self.product(inside_aggregate)
        while self.peek() in ('+', '-'):
            node = Binary(self.take(), node, self.product(inside_aggregate))
        return node

    def product(self, inside_aggregate):
        node = self.atom(inside_aggregate)
        while self.peek() in ('*', '/'):
            node = Binary(self.take(), node, self.atom(inside_aggregate))
        return node

    def atom(self, inside_aggregate):
        token = self.peek()
        if token == '-':
            self.take('-')
            return Unary('-', self.atom(inside_aggregate))
        if token == '(':
            self.take('(')
            node = self.sum_expr(inside_aggregate)
            self.take(')')
            return node
        if token and re.fullmatch(r"\d+(?:\.\d+)?", token):
            return Number(self.take())
        if token and re.fullmatch(r"[A-Za-z_]\w*", token):
            word = self.take()
            if word.upper() in {'SUM', 'COUNT', 'AVG'}:
                if inside_aggregate:
                    raise SemanticError('nested aggregates are unsupported')
                self.take('(')
                distinct = (self.peek() or '').upper() == 'DISTINCT'
                if distinct:
                    self.take('DISTINCT')
                arg = self.sum_expr(True)
                self.take(')')
                if distinct and (word.upper() != 'COUNT' or not isinstance(arg, Column)):
                    raise SemanticError('DISTINCT is supported only for COUNT(column)')
                return Aggregate(word.upper(), arg, distinct)
            if inside_aggregate and self.peek() == '.':
                self.take('.')
                col = self.take()
                if not re.fullmatch(r"[A-Za-z_]\w*", col):
                    raise SemanticError('invalid column identifier')
                return Column(word, col)
            raise SemanticError(f"bare/unknown metric identifier: {word}")
        raise SemanticError(f"unexpected metric expression token: {token!r}")


def contains_aggregate(node) -> bool:
    if isinstance(node, Aggregate):
        return True
    if isinstance(node, Binary):
        return contains_aggregate(node.left) or contains_aggregate(node.right)
    if isinstance(node, Unary):
        return contains_aggregate(node.operand)
    return False


def refs(node) -> set[tuple[str, str]]:
    if isinstance(node, Column):
        return {(node.dataset, node.name)}
    if isinstance(node, Binary):
        return refs(node.left) | refs(node.right)
    if isinstance(node, Aggregate):
        return refs(node.argument)
    if isinstance(node, Unary):
        return refs(node.operand)
    return set()


def compile_expr(node, *, inside_aggregate=False) -> str:
    """All SQL identifiers are validated by the Catalog before reaching this function."""
    from .catalog import identifier

    if isinstance(node, Column):
        return f'{identifier(node.dataset)}.{identifier(node.name)}'
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Aggregate):
        arg = compile_expr(node.argument, inside_aggregate=True)
        return f'{node.function}({"DISTINCT " if node.distinct else ""}{arg})'
    if isinstance(node, Unary):
        return f'(-{compile_expr(node.operand, inside_aggregate=inside_aggregate)})'
    if isinstance(node, Binary):
        left = compile_expr(node.left, inside_aggregate=inside_aggregate)
        right = compile_expr(node.right, inside_aggregate=inside_aggregate)
        if node.op == '/':
            # Guarantee floating-point division, including integer COUNT/COUNT metrics.
            return f'(CAST({left} AS DOUBLE) / NULLIF({right}, 0))'
        return f'({left} {node.op} {right})'
    raise SemanticError('unknown expression AST node')


def parse_metric(source: str):
    return Parser(source).parse()
