Enhance the MiniLang mini compiler with advanced language features.

The project is a complete compiler pipeline (lexer → parser → AST → bytecode compiler → VM)
for a custom scripting language called MiniLang, implemented in pure Python with zero
external dependencies.

Current features:
- Variables (let/assign), integers, floats, strings, booleans, arrays
- Arithmetic (+, -, *, /, %), comparisons, logical operators (and, or, not)
- Control flow: if/else, while, for-in, break, continue
- Functions with recursion
- Built-in functions: len, range, push, pop, str, int, float, abs, min, max, type
- Array indexing and mutation
- Comments (# and //)

Requested enhancements (in order of priority):

1. **String Interpolation (f-strings)**: Add support for f"Hello, {name}!" syntax
   where expressions inside {} are evaluated and converted to strings at runtime.
   This requires changes across the entire pipeline (lexer, parser, compiler, VM).

2. **Closures & First-Class Functions**: Allow functions to be assigned to variables,
   passed as arguments, and returned from other functions. Inner functions should
   capture variables from their enclosing scope (closures). This is a significant
   change requiring a new runtime representation for function values.

3. **Bytecode Optimizer**: Implement an optimization pass that runs between compilation
   and execution. Should include constant folding, dead code elimination, and peephole
   optimizations. Must be semantically preserving (identical output before/after).

All changes must maintain backward compatibility — existing tests must continue to pass.
New test cases must be added for each feature.
