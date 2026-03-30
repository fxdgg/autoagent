"""
Bytecode Compiler for MiniLang.

Walks the AST and emits bytecode instructions for the stack-based VM.
Handles variable scoping, function compilation, and control flow.
"""

from enum import IntEnum, auto
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from ast_nodes import (
    ASTNode, Program, Block,
    IntegerLiteral, FloatLiteral, StringLiteral, BooleanLiteral,
    Identifier, BinaryOp, UnaryOp, ComparisonOp, LogicalOp,
    FunctionCall, ArrayLiteral, IndexAccess,
    LetStatement, AssignStatement, IndexAssignStatement,
    PrintStatement, ReturnStatement, BreakStatement, ContinueStatement,
    ExpressionStatement,
    IfStatement, WhileStatement, ForStatement,
    FunctionDef,
)


class OpCode(IntEnum):
    """Bytecode instruction opcodes."""
    # Stack operations
    LOAD_CONST = auto()      # Push a constant onto the stack
    LOAD_VAR = auto()        # Push a variable's value onto the stack
    STORE_VAR = auto()       # Pop TOS and store into a variable
    POP = auto()             # Discard TOS

    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    NEG = auto()             # Unary negation

    # Comparison
    CMP_EQ = auto()
    CMP_NEQ = auto()
    CMP_LT = auto()
    CMP_GT = auto()
    CMP_LTE = auto()
    CMP_GTE = auto()

    # Logical
    LOGIC_AND = auto()
    LOGIC_OR = auto()
    LOGIC_NOT = auto()

    # Control flow
    JUMP = auto()            # Unconditional jump
    JUMP_IF_FALSE = auto()   # Jump if TOS is falsy (pops TOS)
    JUMP_IF_TRUE = auto()    # Jump if TOS is truthy (pops TOS)

    # Functions
    CALL = auto()            # Call function: arg_count on stack, then func name
    RETURN_VAL = auto()      # Return from function with TOS as return value
    RETURN_NONE = auto()     # Return from function with None

    # Built-in operations
    PRINT = auto()           # Print TOS
    BUILD_ARRAY = auto()     # Build array from N items on stack
    INDEX_GET = auto()        # Get item: array[index]
    INDEX_SET = auto()        # Set item: array[index] = value

    # Iterator support (for-in loops)
    GET_ITER = auto()        # Convert TOS to an iterator
    FOR_ITER = auto()        # Advance iterator; push next value or jump if exhausted

    # Halt
    HALT = auto()


@dataclass
class Instruction:
    """A single bytecode instruction."""
    opcode: OpCode
    operand: Any = None
    line: int = 0

    def __repr__(self):
        if self.operand is not None:
            return f"{self.opcode.name:20s} {self.operand!r}"
        return f"{self.opcode.name}"


@dataclass
class CompiledFunction:
    """A compiled function's bytecode and metadata."""
    name: str
    params: List[str]
    instructions: List[Instruction] = field(default_factory=list)
    constants: List[Any] = field(default_factory=list)
    local_names: List[str] = field(default_factory=list)


@dataclass
class CompiledProgram:
    """The complete compiled program."""
    instructions: List[Instruction] = field(default_factory=list)
    constants: List[Any] = field(default_factory=list)
    functions: Dict[str, CompiledFunction] = field(default_factory=dict)
    global_names: List[str] = field(default_factory=list)


class CompileError(Exception):
    """Raised when the compiler encounters a semantic error."""

    def __init__(self, message: str, node: ASTNode):
        self.node = node
        super().__init__(
            f"CompileError at L{node.line}:C{node.column}: {message}"
        )


class Compiler:
    """
    Compiles a MiniLang AST into bytecode.

    Usage:
        compiler = Compiler()
        program = compiler.compile(ast)
    """

    def __init__(self):
        self.instructions: List[Instruction] = []
        self.constants: List[Any] = []
        self.functions: Dict[str, CompiledFunction] = {}
        self.global_names: List[str] = []

        # State for compiling functions
        self._compiling_function: Optional[CompiledFunction] = None
        self._loop_start_stack: List[int] = []
        self._loop_break_patches: List[List[int]] = []

    @property
    def _current_instructions(self) -> List[Instruction]:
        if self._compiling_function:
            return self._compiling_function.instructions
        return self.instructions

    @property
    def _current_constants(self) -> List[Any]:
        if self._compiling_function:
            return self._compiling_function.constants
        return self.constants

    def _emit(self, opcode: OpCode, operand: Any = None, line: int = 0) -> int:
        """Emit an instruction and return its index."""
        instr = Instruction(opcode=opcode, operand=operand, line=line)
        instrs = self._current_instructions
        instrs.append(instr)
        return len(instrs) - 1

    def _add_constant(self, value: Any) -> int:
        """Add a constant to the pool and return its index."""
        consts = self._current_constants
        # Reuse existing constant if possible
        for i, c in enumerate(consts):
            if c == value and type(c) is type(value):
                return i
        consts.append(value)
        return len(consts) - 1

    def _patch_jump(self, instr_index: int, target: int = None):
        """Patch a jump instruction's operand to point to target (or current pos)."""
        instrs = self._current_instructions
        if target is None:
            target = len(instrs)
        instrs[instr_index].operand = target

    def compile(self, program: Program) -> CompiledProgram:
        """Compile a Program AST into a CompiledProgram."""
        # First pass: compile all function definitions
        for stmt in program.statements:
            if isinstance(stmt, FunctionDef):
                self._compile_function_def(stmt)

        # Second pass: compile top-level statements
        for stmt in program.statements:
            if not isinstance(stmt, FunctionDef):
                self._compile_node(stmt)

        self._emit(OpCode.HALT)

        return CompiledProgram(
            instructions=self.instructions,
            constants=self.constants,
            functions=self.functions,
            global_names=self.global_names,
        )

    def _compile_function_def(self, node: FunctionDef):
        """Compile a function definition into a CompiledFunction."""
        if node.name in self.functions:
            raise CompileError(f"Function '{node.name}' already defined", node)

        func = CompiledFunction(
            name=node.name,
            params=list(node.params),
            local_names=list(node.params),
        )

        # Switch context to function compilation
        prev_func = self._compiling_function
        self._compiling_function = func

        # Compile function body
        for stmt in node.body.statements:
            self._compile_node(stmt)

        # Ensure function ends with a return
        if not func.instructions or func.instructions[-1].opcode not in (
            OpCode.RETURN_VAL, OpCode.RETURN_NONE
        ):
            self._emit(OpCode.RETURN_NONE, line=node.line)

        # Restore context
        self._compiling_function = prev_func
        self.functions[node.name] = func

    def _compile_node(self, node: ASTNode):
        """Dispatch compilation to the appropriate method."""
        method_name = f"_compile_{type(node).__name__}"
        method = getattr(self, method_name, None)
        if method is None:
            raise CompileError(f"Cannot compile node type: {type(node).__name__}", node)
        method(node)

    # ---- Statements ----

    def _compile_LetStatement(self, node: LetStatement):
        self._compile_node(node.value)
        self._register_variable(node.name)
        self._emit(OpCode.STORE_VAR, node.name, line=node.line)

    def _compile_AssignStatement(self, node: AssignStatement):
        self._compile_node(node.value)
        self._emit(OpCode.STORE_VAR, node.name, line=node.line)

    def _compile_IndexAssignStatement(self, node: IndexAssignStatement):
        self._compile_node(node.obj)
        self._compile_node(node.index)
        self._compile_node(node.value)
        self._emit(OpCode.INDEX_SET, line=node.line)

    def _compile_PrintStatement(self, node: PrintStatement):
        self._compile_node(node.expression)
        self._emit(OpCode.PRINT, line=node.line)

    def _compile_ReturnStatement(self, node: ReturnStatement):
        if node.value is not None:
            self._compile_node(node.value)
            self._emit(OpCode.RETURN_VAL, line=node.line)
        else:
            self._emit(OpCode.RETURN_NONE, line=node.line)

    def _compile_BreakStatement(self, node: BreakStatement):
        if not self._loop_break_patches:
            raise CompileError("'break' outside of loop", node)
        idx = self._emit(OpCode.JUMP, 0, line=node.line)  # placeholder
        self._loop_break_patches[-1].append(idx)

    def _compile_ContinueStatement(self, node: ContinueStatement):
        if not self._loop_start_stack:
            raise CompileError("'continue' outside of loop", node)
        self._emit(OpCode.JUMP, self._loop_start_stack[-1], line=node.line)

    def _compile_ExpressionStatement(self, node: ExpressionStatement):
        self._compile_node(node.expression)
        self._emit(OpCode.POP, line=node.line)

    def _compile_Block(self, node: Block):
        for stmt in node.statements:
            self._compile_node(stmt)

    # ---- Control Flow ----

    def _compile_IfStatement(self, node: IfStatement):
        self._compile_node(node.condition)
        jump_false = self._emit(OpCode.JUMP_IF_FALSE, 0, line=node.line)

        # Then block
        self._compile_Block(node.then_block)

        if node.else_block:
            jump_end = self._emit(OpCode.JUMP, 0, line=node.line)
            self._patch_jump(jump_false)
            self._compile_Block(node.else_block)
            self._patch_jump(jump_end)
        else:
            self._patch_jump(jump_false)

    def _compile_WhileStatement(self, node: WhileStatement):
        loop_start = len(self._current_instructions)
        self._loop_start_stack.append(loop_start)
        self._loop_break_patches.append([])

        self._compile_node(node.condition)
        jump_false = self._emit(OpCode.JUMP_IF_FALSE, 0, line=node.line)

        self._compile_Block(node.body)
        self._emit(OpCode.JUMP, loop_start, line=node.line)

        self._patch_jump(jump_false)

        # Patch all break statements
        for break_idx in self._loop_break_patches.pop():
            self._patch_jump(break_idx)
        self._loop_start_stack.pop()

    def _compile_ForStatement(self, node: ForStatement):
        # Compile iterable and get iterator
        self._compile_node(node.iterable)
        self._emit(OpCode.GET_ITER, line=node.line)

        loop_start = len(self._current_instructions)
        self._loop_start_stack.append(loop_start)
        self._loop_break_patches.append([])

        # FOR_ITER: push next value or jump to end
        jump_end = self._emit(OpCode.FOR_ITER, 0, line=node.line)

        # Store loop variable
        self._register_variable(node.var_name)
        self._emit(OpCode.STORE_VAR, node.var_name, line=node.line)

        # Compile body
        self._compile_Block(node.body)
        self._emit(OpCode.JUMP, loop_start, line=node.line)

        self._patch_jump(jump_end)
        # Pop the exhausted iterator
        self._emit(OpCode.POP, line=node.line)

        # Patch break statements
        for break_idx in self._loop_break_patches.pop():
            self._patch_jump(break_idx)
        self._loop_start_stack.pop()

    # ---- Expressions ----

    def _compile_IntegerLiteral(self, node: IntegerLiteral):
        idx = self._add_constant(node.value)
        self._emit(OpCode.LOAD_CONST, idx, line=node.line)

    def _compile_FloatLiteral(self, node: FloatLiteral):
        idx = self._add_constant(node.value)
        self._emit(OpCode.LOAD_CONST, idx, line=node.line)

    def _compile_StringLiteral(self, node: StringLiteral):
        idx = self._add_constant(node.value)
        self._emit(OpCode.LOAD_CONST, idx, line=node.line)

    def _compile_BooleanLiteral(self, node: BooleanLiteral):
        idx = self._add_constant(node.value)
        self._emit(OpCode.LOAD_CONST, idx, line=node.line)

    def _compile_Identifier(self, node: Identifier):
        self._emit(OpCode.LOAD_VAR, node.name, line=node.line)

    def _compile_BinaryOp(self, node: BinaryOp):
        self._compile_node(node.left)
        self._compile_node(node.right)
        op_map = {
            "+": OpCode.ADD,
            "-": OpCode.SUB,
            "*": OpCode.MUL,
            "/": OpCode.DIV,
            "%": OpCode.MOD,
        }
        if node.op not in op_map:
            raise CompileError(f"Unknown binary operator: {node.op}", node)
        self._emit(op_map[node.op], line=node.line)

    def _compile_UnaryOp(self, node: UnaryOp):
        self._compile_node(node.operand)
        if node.op == "-":
            self._emit(OpCode.NEG, line=node.line)
        elif node.op == "not":
            self._emit(OpCode.LOGIC_NOT, line=node.line)
        else:
            raise CompileError(f"Unknown unary operator: {node.op}", node)

    def _compile_ComparisonOp(self, node: ComparisonOp):
        self._compile_node(node.left)
        self._compile_node(node.right)
        op_map = {
            "==": OpCode.CMP_EQ,
            "!=": OpCode.CMP_NEQ,
            "<": OpCode.CMP_LT,
            ">": OpCode.CMP_GT,
            "<=": OpCode.CMP_LTE,
            ">=": OpCode.CMP_GTE,
        }
        if node.op not in op_map:
            raise CompileError(f"Unknown comparison operator: {node.op}", node)
        self._emit(op_map[node.op], line=node.line)

    def _compile_LogicalOp(self, node: LogicalOp):
        self._compile_node(node.left)
        self._compile_node(node.right)
        if node.op == "and":
            self._emit(OpCode.LOGIC_AND, line=node.line)
        elif node.op == "or":
            self._emit(OpCode.LOGIC_OR, line=node.line)
        else:
            raise CompileError(f"Unknown logical operator: {node.op}", node)

    def _compile_FunctionCall(self, node: FunctionCall):
        # Push arguments onto stack
        for arg in node.arguments:
            self._compile_node(arg)
        # Emit CALL with function name and arg count
        self._emit(OpCode.CALL, (node.name, len(node.arguments)), line=node.line)

    def _compile_ArrayLiteral(self, node: ArrayLiteral):
        for elem in node.elements:
            self._compile_node(elem)
        self._emit(OpCode.BUILD_ARRAY, len(node.elements), line=node.line)

    def _compile_IndexAccess(self, node: IndexAccess):
        self._compile_node(node.obj)
        self._compile_node(node.index)
        self._emit(OpCode.INDEX_GET, line=node.line)

    # ---- Helpers ----

    def _register_variable(self, name: str):
        """Register a variable name in the current scope."""
        if self._compiling_function:
            if name not in self._compiling_function.local_names:
                self._compiling_function.local_names.append(name)
        else:
            if name not in self.global_names:
                self.global_names.append(name)


def disassemble(program: CompiledProgram) -> str:
    """Pretty-print the bytecode of a compiled program."""
    lines = []
    lines.append("=== Main Program ===")
    lines.append(f"Constants: {program.constants}")
    lines.append(f"Globals:   {program.global_names}")
    lines.append("")
    for i, instr in enumerate(program.instructions):
        operand_str = ""
        if instr.operand is not None:
            if instr.opcode == OpCode.LOAD_CONST:
                operand_str = f" {instr.operand} ({program.constants[instr.operand]!r})"
            else:
                operand_str = f" {instr.operand!r}"
        lines.append(f"  {i:4d}  {instr.opcode.name:20s}{operand_str}")

    for name, func in program.functions.items():
        lines.append("")
        lines.append(f"=== Function '{name}' (params: {func.params}) ===")
        lines.append(f"Constants: {func.constants}")
        lines.append(f"Locals:    {func.local_names}")
        lines.append("")
        for i, instr in enumerate(func.instructions):
            operand_str = ""
            if instr.operand is not None:
                if instr.opcode == OpCode.LOAD_CONST:
                    operand_str = f" {instr.operand} ({func.constants[instr.operand]!r})"
                else:
                    operand_str = f" {instr.operand!r}"
            lines.append(f"  {i:4d}  {instr.opcode.name:20s}{operand_str}")

    return "\n".join(lines)
