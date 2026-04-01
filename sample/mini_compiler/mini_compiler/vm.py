"""
Stack-based Virtual Machine for MiniLang.

Executes bytecode produced by the Compiler. Features:
- Stack-based evaluation
- Global and local variable scopes
- Function call frames with return values
- Built-in functions (len, range, push, pop, str, int, float, abs, min, max)
- Array operations
- Iterator protocol for for-in loops
"""

from typing import List, Dict, Any, Optional
from compiler import OpCode, CompiledProgram, CompiledFunction, Instruction


class VMError(Exception):
    """Raised when the VM encounters a runtime error."""

    def __init__(self, message: str, line: int = 0):
        self.vm_line = line
        super().__init__(f"RuntimeError at line {line}: {message}")


class CallFrame:
    """Represents a function call on the call stack."""

    def __init__(self, func: CompiledFunction, return_addr: int,
                 locals_dict: Dict[str, Any]):
        self.func = func
        self.return_addr = return_addr
        self.locals = locals_dict
        self.ip = 0  # instruction pointer within this function


class ArrayIterator:
    """Iterator wrapper for arrays in for-in loops."""

    def __init__(self, data):
        self.data = data
        self.index = 0

    def has_next(self) -> bool:
        return self.index < len(self.data)

    def next_value(self):
        val = self.data[self.index]
        self.index += 1
        return val


class VM:
    """
    Stack-based virtual machine for MiniLang bytecode.

    Usage:
        vm = VM(compiled_program)
        vm.run()
        output = vm.get_output()
    """

    MAX_STACK_SIZE = 10000
    MAX_CALL_DEPTH = 256
    MAX_INSTRUCTIONS = 1_000_000  # Prevent infinite loops

    def __init__(self, program: CompiledProgram):
        self.program = program
        self.stack: List[Any] = []
        self.globals: Dict[str, Any] = {}
        self.call_stack: List[CallFrame] = []
        self.ip = 0  # instruction pointer for main program
        self.output: List[str] = []
        self.instruction_count = 0
        self.halted = False

        # Built-in functions
        self.builtins = {
            "len": self._builtin_len,
            "range": self._builtin_range,
            "push": self._builtin_push,
            "pop": self._builtin_pop,
            "str": self._builtin_str,
            "int": self._builtin_int,
            "float": self._builtin_float,
            "abs": self._builtin_abs,
            "min": self._builtin_min,
            "max": self._builtin_max,
            "type": self._builtin_type,
            "input": self._builtin_input,
        }

    def _push(self, value: Any):
        if len(self.stack) >= self.MAX_STACK_SIZE:
            raise VMError("Stack overflow")
        self.stack.append(value)

    def _pop(self) -> Any:
        if not self.stack:
            raise VMError("Stack underflow")
        return self.stack.pop()

    def _peek(self) -> Any:
        if not self.stack:
            raise VMError("Stack underflow (peek)")
        return self.stack[-1]

    def _get_var(self, name: str) -> Any:
        """Look up a variable: local scope first, then global."""
        if self.call_stack:
            frame = self.call_stack[-1]
            if name in frame.locals:
                return frame.locals[name]
        if name in self.globals:
            return self.globals[name]
        raise VMError(f"Undefined variable: '{name}'")

    def _set_var(self, name: str, value: Any):
        """Set a variable in the current scope."""
        if self.call_stack:
            frame = self.call_stack[-1]
            # If it's a known local or a new variable in function scope
            if name in frame.func.local_names or name not in self.globals:
                frame.locals[name] = value
                return
        self.globals[name] = value

    def _get_instructions(self) -> List[Instruction]:
        if self.call_stack:
            return self.call_stack[-1].func.instructions
        return self.program.instructions

    def _get_constants(self) -> List[Any]:
        if self.call_stack:
            return self.call_stack[-1].func.constants
        return self.program.constants

    def _get_ip(self) -> int:
        if self.call_stack:
            return self.call_stack[-1].ip
        return self.ip

    def _set_ip(self, value: int):
        if self.call_stack:
            self.call_stack[-1].ip = value
        else:
            self.ip = value

    def run(self):
        """Execute the program until HALT or completion."""
        while not self.halted:
            self.instruction_count += 1
            if self.instruction_count > self.MAX_INSTRUCTIONS:
                raise VMError("Execution limit exceeded (possible infinite loop)")

            instructions = self._get_instructions()
            ip = self._get_ip()

            if ip >= len(instructions):
                if self.call_stack:
                    # Implicit return from function
                    self._push(None)
                    self._return_from_function()
                    continue
                else:
                    break

            instr = instructions[ip]
            self._set_ip(ip + 1)
            self._execute(instr)

    def _execute(self, instr: Instruction):
        """Execute a single instruction."""
        op = instr.opcode

        if op == OpCode.LOAD_CONST:
            self._push(self._get_constants()[instr.operand])

        elif op == OpCode.LOAD_VAR:
            self._push(self._get_var(instr.operand))

        elif op == OpCode.STORE_VAR:
            self._set_var(instr.operand, self._pop())

        elif op == OpCode.POP:
            self._pop()

        # Arithmetic
        elif op == OpCode.ADD:
            b, a = self._pop(), self._pop()
            self._push(a + b)
        elif op == OpCode.SUB:
            b, a = self._pop(), self._pop()
            self._push(a - b)
        elif op == OpCode.MUL:
            b, a = self._pop(), self._pop()
            self._push(a * b)
        elif op == OpCode.DIV:
            b, a = self._pop(), self._pop()
            if b == 0:
                raise VMError("Division by zero", instr.line)
            # Integer division if both are ints
            if isinstance(a, int) and isinstance(b, int):
                self._push(a // b)
            else:
                self._push(a / b)
        elif op == OpCode.MOD:
            b, a = self._pop(), self._pop()
            if b == 0:
                raise VMError("Modulo by zero", instr.line)
            self._push(a % b)
        elif op == OpCode.NEG:
            self._push(-self._pop())

        # Comparison
        elif op == OpCode.CMP_EQ:
            b, a = self._pop(), self._pop()
            self._push(a == b)
        elif op == OpCode.CMP_NEQ:
            b, a = self._pop(), self._pop()
            self._push(a != b)
        elif op == OpCode.CMP_LT:
            b, a = self._pop(), self._pop()
            self._push(a < b)
        elif op == OpCode.CMP_GT:
            b, a = self._pop(), self._pop()
            self._push(a > b)
        elif op == OpCode.CMP_LTE:
            b, a = self._pop(), self._pop()
            self._push(a <= b)
        elif op == OpCode.CMP_GTE:
            b, a = self._pop(), self._pop()
            self._push(a >= b)

        # Logical
        elif op == OpCode.LOGIC_AND:
            b, a = self._pop(), self._pop()
            self._push(bool(a) and bool(b))
        elif op == OpCode.LOGIC_OR:
            b, a = self._pop(), self._pop()
            self._push(bool(a) or bool(b))
        elif op == OpCode.LOGIC_NOT:
            self._push(not bool(self._pop()))

        # Control flow
        elif op == OpCode.JUMP:
            self._set_ip(instr.operand)
        elif op == OpCode.JUMP_IF_FALSE:
            if not bool(self._pop()):
                self._set_ip(instr.operand)
        elif op == OpCode.JUMP_IF_TRUE:
            if bool(self._pop()):
                self._set_ip(instr.operand)

        # Functions
        elif op == OpCode.CALL:
            func_name, arg_count = instr.operand
            self._call_function(func_name, arg_count, instr.line)
        elif op == OpCode.RETURN_VAL:
            self._return_from_function()
        elif op == OpCode.RETURN_NONE:
            self._push(None)
            self._return_from_function()

        # Built-ins
        elif op == OpCode.PRINT:
            value = self._pop()
            output_str = self._format_value(value)
            self.output.append(output_str)

        elif op == OpCode.BUILD_ARRAY:
            count = instr.operand
            elements = []
            for _ in range(count):
                elements.append(self._pop())
            elements.reverse()
            self._push(elements)

        elif op == OpCode.INDEX_GET:
            index = self._pop()
            obj = self._pop()
            if not isinstance(obj, list):
                raise VMError(f"Cannot index non-array type: {type(obj).__name__}", instr.line)
            if not isinstance(index, int):
                raise VMError(f"Array index must be integer, got {type(index).__name__}", instr.line)
            if index < 0 or index >= len(obj):
                raise VMError(f"Array index out of bounds: {index} (length {len(obj)})", instr.line)
            self._push(obj[index])

        elif op == OpCode.INDEX_SET:
            value = self._pop()
            index = self._pop()
            obj = self._pop()
            if not isinstance(obj, list):
                raise VMError(f"Cannot index non-array type: {type(obj).__name__}", instr.line)
            if not isinstance(index, int):
                raise VMError(f"Array index must be integer, got {type(index).__name__}", instr.line)
            if index < 0 or index >= len(obj):
                raise VMError(f"Array index out of bounds: {index} (length {len(obj)})", instr.line)
            obj[index] = value

        # Iterator
        elif op == OpCode.GET_ITER:
            obj = self._pop()
            if isinstance(obj, list):
                self._push(ArrayIterator(obj))
            else:
                raise VMError(f"Cannot iterate over {type(obj).__name__}", instr.line)

        elif op == OpCode.FOR_ITER:
            iterator = self._peek()
            if isinstance(iterator, ArrayIterator):
                if iterator.has_next():
                    self._push(iterator.next_value())
                else:
                    self._set_ip(instr.operand)
            else:
                raise VMError("Invalid iterator on stack", instr.line)

        elif op == OpCode.HALT:
            self.halted = True

        else:
            raise VMError(f"Unknown opcode: {op}", instr.line)

    def _call_function(self, name: str, arg_count: int, line: int):
        """Handle function calls (user-defined and built-in)."""
        # Check built-in functions first
        if name in self.builtins:
            args = []
            for _ in range(arg_count):
                args.append(self._pop())
            args.reverse()
            result = self.builtins[name](args, line)
            self._push(result)
            return

        # User-defined function
        if name not in self.program.functions:
            raise VMError(f"Undefined function: '{name}'", line)

        func = self.program.functions[name]
        if arg_count != len(func.params):
            raise VMError(
                f"Function '{name}' expects {len(func.params)} arguments, got {arg_count}",
                line
            )

        if len(self.call_stack) >= self.MAX_CALL_DEPTH:
            raise VMError("Maximum call depth exceeded (possible infinite recursion)", line)

        # Pop arguments and bind to parameters
        args = []
        for _ in range(arg_count):
            args.append(self._pop())
        args.reverse()

        locals_dict = {}
        for param_name, arg_val in zip(func.params, args):
            locals_dict[param_name] = arg_val

        # Save current IP as return address
        return_addr = self._get_ip()

        frame = CallFrame(func=func, return_addr=return_addr, locals_dict=locals_dict)
        self.call_stack.append(frame)

    def _return_from_function(self):
        """Return from the current function."""
        return_value = self._pop()
        frame = self.call_stack.pop()

        # Restore IP
        if self.call_stack:
            self.call_stack[-1].ip = frame.return_addr
        else:
            self.ip = frame.return_addr

        self._push(return_value)

    def _format_value(self, value: Any) -> str:
        """Format a value for printing."""
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            inner = ", ".join(self._format_value(v) for v in value)
            return f"[{inner}]"
        if isinstance(value, float):
            # Clean float display
            if value == int(value):
                return f"{value:.1f}"
            return str(value)
        return str(value)

    def get_output(self) -> List[str]:
        """Return all printed output lines."""
        return self.output

    # ---- Built-in Functions ----

    def _builtin_len(self, args: List[Any], line: int) -> int:
        if len(args) != 1:
            raise VMError("len() takes exactly 1 argument", line)
        obj = args[0]
        if isinstance(obj, (list, str)):
            return len(obj)
        raise VMError(f"len() not supported for type {type(obj).__name__}", line)

    def _builtin_range(self, args: List[Any], line: int) -> list:
        if len(args) == 1:
            return list(range(int(args[0])))
        elif len(args) == 2:
            return list(range(int(args[0]), int(args[1])))
        elif len(args) == 3:
            return list(range(int(args[0]), int(args[1]), int(args[2])))
        raise VMError("range() takes 1 to 3 arguments", line)

    def _builtin_push(self, args: List[Any], line: int) -> Any:
        if len(args) != 2:
            raise VMError("push() takes exactly 2 arguments (array, value)", line)
        arr, val = args
        if not isinstance(arr, list):
            raise VMError("push() first argument must be an array", line)
        arr.append(val)
        return None

    def _builtin_pop(self, args: List[Any], line: int) -> Any:
        if len(args) != 1:
            raise VMError("pop() takes exactly 1 argument (array)", line)
        arr = args[0]
        if not isinstance(arr, list):
            raise VMError("pop() argument must be an array", line)
        if len(arr) == 0:
            raise VMError("pop() on empty array", line)
        return arr.pop()

    def _builtin_str(self, args: List[Any], line: int) -> str:
        if len(args) != 1:
            raise VMError("str() takes exactly 1 argument", line)
        return self._format_value(args[0])

    def _builtin_int(self, args: List[Any], line: int) -> int:
        if len(args) != 1:
            raise VMError("int() takes exactly 1 argument", line)
        try:
            return int(args[0])
        except (ValueError, TypeError):
            raise VMError(f"Cannot convert {args[0]!r} to int", line)

    def _builtin_float(self, args: List[Any], line: int) -> float:
        if len(args) != 1:
            raise VMError("float() takes exactly 1 argument", line)
        try:
            return float(args[0])
        except (ValueError, TypeError):
            raise VMError(f"Cannot convert {args[0]!r} to float", line)

    def _builtin_abs(self, args: List[Any], line: int) -> Any:
        if len(args) != 1:
            raise VMError("abs() takes exactly 1 argument", line)
        return abs(args[0])

    def _builtin_min(self, args: List[Any], line: int) -> Any:
        if len(args) == 1 and isinstance(args[0], list):
            if not args[0]:
                raise VMError("min() on empty array", line)
            return min(args[0])
        if len(args) >= 2:
            return min(args)
        raise VMError("min() requires at least 2 arguments or 1 array", line)

    def _builtin_max(self, args: List[Any], line: int) -> Any:
        if len(args) == 1 and isinstance(args[0], list):
            if not args[0]:
                raise VMError("max() on empty array", line)
            return max(args[0])
        if len(args) >= 2:
            return max(args)
        raise VMError("max() requires at least 2 arguments or 1 array", line)

    def _builtin_type(self, args: List[Any], line: int) -> str:
        if len(args) != 1:
            raise VMError("type() takes exactly 1 argument", line)
        val = args[0]
        if val is None:
            return "None"
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, int):
            return "int"
        if isinstance(val, float):
            return "float"
        if isinstance(val, str):
            return "string"
        if isinstance(val, list):
            return "array"
        return type(val).__name__

    def _builtin_input(self, args: List[Any], line: int) -> str:
        # In non-interactive mode, return empty string
        return ""
