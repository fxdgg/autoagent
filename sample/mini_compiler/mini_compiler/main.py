#!/usr/bin/env python3
"""
MiniLang — A mini programming language with compiler and VM.

This is the main entry point. It reads a .mini source file, tokenizes it,
parses it into an AST, compiles it to bytecode, and executes it on the VM.

Usage:
    python main.py <source_file.mini>
    python main.py <source_file.mini> --disasm     # Show bytecode disassembly
    python main.py <source_file.mini> --ast        # Show AST dump
    python main.py <source_file.mini> --tokens     # Show token stream
"""

import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lexer import Lexer, LexerError
from parser import Parser, ParseError
from compiler import Compiler, CompileError, disassemble
from vm import VM, VMError


def dump_ast(node, indent=0):
    """Pretty-print an AST node recursively."""
    prefix = "  " * indent
    name = type(node).__name__
    fields = []
    for key, val in vars(node).items():
        if key in ("line", "column"):
            continue
        if isinstance(val, list):
            if val and hasattr(val[0], "line"):
                fields.append(f"{key}=[...]")
            else:
                fields.append(f"{key}={val!r}")
        elif hasattr(val, "line"):
            fields.append(f"{key}=<{type(val).__name__}>")
        else:
            fields.append(f"{key}={val!r}")
    print(f"{prefix}{name}({', '.join(fields)})")

    for key, val in vars(node).items():
        if key in ("line", "column"):
            continue
        if isinstance(val, list):
            for item in val:
                if hasattr(item, "line"):
                    dump_ast(item, indent + 1)
        elif hasattr(val, "line") and val is not None:
            dump_ast(val, indent + 1)


def run_source(source: str, filename: str = "<stdin>",
               show_tokens: bool = False, show_ast: bool = False,
               show_disasm: bool = False) -> list:
    """
    Run a MiniLang source string through the full pipeline.
    Returns the list of output lines from the VM.
    """
    # Step 1: Tokenize
    lexer = Lexer(source)
    tokens = lexer.tokenize()

    if show_tokens:
        print("=== Tokens ===")
        for tok in tokens:
            print(f"  {tok}")
        print()

    # Step 2: Parse
    parser = Parser(tokens)
    ast = parser.parse()

    if show_ast:
        print("=== AST ===")
        dump_ast(ast)
        print()

    # Step 3: Compile
    compiler = Compiler()
    program = compiler.compile(ast)

    if show_disasm:
        print("=== Bytecode ===")
        print(disassemble(program))
        print()

    # Step 4: Execute
    vm = VM(program)
    vm.run()

    return vm.get_output()


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <source_file.mini> [--tokens] [--ast] [--disasm]")
        print()
        print("MiniLang Compiler & VM")
        print("  Compiles .mini source files to bytecode and executes them.")
        sys.exit(1)

    filename = sys.argv[1]
    show_tokens = "--tokens" in sys.argv
    show_ast = "--ast" in sys.argv
    show_disasm = "--disasm" in sys.argv

    try:
        with open(filename, "r", encoding="utf-8") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {filename}")
        sys.exit(1)

    try:
        output = run_source(
            source, filename,
            show_tokens=show_tokens,
            show_ast=show_ast,
            show_disasm=show_disasm,
        )
        for line in output:
            print(line)
    except LexerError as e:
        print(f"[Lexer Error] {e}", file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(f"[Parse Error] {e}", file=sys.stderr)
        sys.exit(1)
    except CompileError as e:
        print(f"[Compile Error] {e}", file=sys.stderr)
        sys.exit(1)
    except VMError as e:
        print(f"[Runtime Error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
