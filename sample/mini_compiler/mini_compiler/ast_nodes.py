"""
AST Node definitions for MiniLang.

Each node represents a syntactic construct in the language.
The AST is produced by the parser and consumed by the compiler.
"""

from dataclasses import dataclass, field
from typing import List, Optional


# ---------- Base ----------

@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    line: int = 0
    column: int = 0


# ---------- Expressions ----------

@dataclass
class IntegerLiteral(ASTNode):
    value: int = 0


@dataclass
class FloatLiteral(ASTNode):
    value: float = 0.0


@dataclass
class StringLiteral(ASTNode):
    value: str = ""


@dataclass
class BooleanLiteral(ASTNode):
    value: bool = False


@dataclass
class Identifier(ASTNode):
    name: str = ""


@dataclass
class BinaryOp(ASTNode):
    """Binary operation: left op right"""
    op: str = ""
    left: ASTNode = None
    right: ASTNode = None


@dataclass
class UnaryOp(ASTNode):
    """Unary operation: op operand"""
    op: str = ""
    operand: ASTNode = None


@dataclass
class ComparisonOp(ASTNode):
    """Comparison: left op right"""
    op: str = ""
    left: ASTNode = None
    right: ASTNode = None


@dataclass
class LogicalOp(ASTNode):
    """Logical operation: left (and/or) right"""
    op: str = ""
    left: ASTNode = None
    right: ASTNode = None


@dataclass
class FunctionCall(ASTNode):
    """Function call: name(args...)"""
    name: str = ""
    arguments: List[ASTNode] = field(default_factory=list)


@dataclass
class ArrayLiteral(ASTNode):
    """Array literal: [elem1, elem2, ...]"""
    elements: List[ASTNode] = field(default_factory=list)


@dataclass
class IndexAccess(ASTNode):
    """Array index access: obj[index]"""
    obj: ASTNode = None
    index: ASTNode = None


# ---------- Statements ----------

@dataclass
class LetStatement(ASTNode):
    """Variable declaration: let name = value"""
    name: str = ""
    value: ASTNode = None


@dataclass
class AssignStatement(ASTNode):
    """Variable assignment: name = value"""
    name: str = ""
    value: ASTNode = None


@dataclass
class IndexAssignStatement(ASTNode):
    """Array index assignment: obj[index] = value"""
    obj: ASTNode = None
    index: ASTNode = None
    value: ASTNode = None


@dataclass
class PrintStatement(ASTNode):
    """Print statement: print(expr)"""
    expression: ASTNode = None


@dataclass
class ReturnStatement(ASTNode):
    """Return statement: return expr"""
    value: Optional[ASTNode] = None


@dataclass
class BreakStatement(ASTNode):
    """Break statement: break"""
    pass


@dataclass
class ContinueStatement(ASTNode):
    """Continue statement: continue"""
    pass


@dataclass
class ExpressionStatement(ASTNode):
    """An expression used as a statement (e.g., function call)."""
    expression: ASTNode = None


# ---------- Control Flow ----------

@dataclass
class Block(ASTNode):
    """A block of statements: { stmt1; stmt2; ... }"""
    statements: List[ASTNode] = field(default_factory=list)


@dataclass
class IfStatement(ASTNode):
    """If statement: if (cond) { ... } else { ... }"""
    condition: ASTNode = None
    then_block: Block = None
    else_block: Optional[Block] = None


@dataclass
class WhileStatement(ASTNode):
    """While loop: while (cond) { ... }"""
    condition: ASTNode = None
    body: Block = None


@dataclass
class ForStatement(ASTNode):
    """For-in loop: for (name in iterable) { ... }"""
    var_name: str = ""
    iterable: ASTNode = None
    body: Block = None


# ---------- Functions ----------

@dataclass
class FunctionDef(ASTNode):
    """Function definition: fn name(params...) { ... }"""
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: Block = None


# ---------- Program ----------

@dataclass
class Program(ASTNode):
    """Top-level program: a list of statements and function definitions."""
    statements: List[ASTNode] = field(default_factory=list)
