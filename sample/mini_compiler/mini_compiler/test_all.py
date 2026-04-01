#!/usr/bin/env python3
"""
Comprehensive test suite for MiniLang compiler.

Tests all components: Lexer, Parser, Compiler, and VM.
Runs without any external dependencies (uses only Python stdlib).

Exit code 0 = all tests pass, non-zero = failures.
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lexer import Lexer, LexerError
from parser import Parser, ParseError
from compiler import Compiler, CompileError
from vm import VM, VMError


class TestRunner:
    """Simple test runner that tracks pass/fail counts."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def run_test(self, name: str, source: str, expected_output: list):
        """Run a MiniLang program and check its output."""
        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            ast = parser.parse()
            compiler = Compiler()
            program = compiler.compile(ast)
            vm = VM(program)
            vm.run()
            actual = vm.get_output()

            if actual == expected_output:
                self.passed += 1
                print(f"  ✓ {name}")
            else:
                self.failed += 1
                self.errors.append(name)
                print(f"  ✗ {name}")
                print(f"    Expected: {expected_output}")
                print(f"    Actual:   {actual}")
        except Exception as e:
            self.failed += 1
            self.errors.append(name)
            print(f"  ✗ {name} (EXCEPTION)")
            print(f"    {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)

    def run_error_test(self, name: str, source: str, error_type):
        """Run a MiniLang program and expect a specific error."""
        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            ast = parser.parse()
            compiler = Compiler()
            program = compiler.compile(ast)
            vm = VM(program)
            vm.run()
            # If we get here, no error was raised
            self.failed += 1
            self.errors.append(name)
            print(f"  ✗ {name} (expected {error_type.__name__}, got no error)")
        except error_type:
            self.passed += 1
            print(f"  ✓ {name}")
        except Exception as e:
            self.failed += 1
            self.errors.append(name)
            print(f"  ✗ {name} (expected {error_type.__name__}, got {type(e).__name__}: {e})")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print(f"Failed tests: {', '.join(self.errors)}")
        print(f"{'='*60}")
        return self.failed == 0


def main():
    runner = TestRunner()

    # ==================== Basic Arithmetic ====================
    print("\n--- Basic Arithmetic ---")

    runner.run_test("Integer addition", """
        print(1 + 2)
    """, ["3"])

    runner.run_test("Integer subtraction", """
        print(10 - 3)
    """, ["7"])

    runner.run_test("Integer multiplication", """
        print(4 * 5)
    """, ["20"])

    runner.run_test("Integer division", """
        print(10 / 3)
    """, ["3"])

    runner.run_test("Modulo", """
        print(10 % 3)
    """, ["1"])

    runner.run_test("Operator precedence", """
        print(2 + 3 * 4)
    """, ["14"])

    runner.run_test("Parentheses", """
        print((2 + 3) * 4)
    """, ["20"])

    runner.run_test("Unary negation", """
        print(-5)
        print(-(3 + 2))
    """, ["-5", "-5"])

    runner.run_test("Complex expression", """
        print(2 * (3 + 4) - 10 / 2)
    """, ["9"])

    runner.run_test("Float arithmetic", """
        print(3.14 * 2.0)
    """, ["6.28"])

    # ==================== Variables ====================
    print("\n--- Variables ---")

    runner.run_test("Variable declaration and use", """
        let x = 42
        print(x)
    """, ["42"])

    runner.run_test("Variable reassignment", """
        let x = 10
        x = 20
        print(x)
    """, ["20"])

    runner.run_test("Multiple variables", """
        let a = 5
        let b = 10
        let c = a + b
        print(c)
    """, ["15"])

    runner.run_test("Variable in expression", """
        let x = 3
        let y = 4
        print(x * x + y * y)
    """, ["25"])

    # ==================== Strings ====================
    print("\n--- Strings ---")

    runner.run_test("String literal", """
        print("hello world")
    """, ["hello world"])

    runner.run_test("String concatenation", """
        print("hello" + " " + "world")
    """, ["hello world"])

    runner.run_test("String with escape", """
        print("line1\\nline2")
    """, ["line1\nline2"])

    runner.run_test("String length", """
        print(len("hello"))
    """, ["5"])

    # ==================== Booleans & Comparisons ====================
    print("\n--- Booleans & Comparisons ---")

    runner.run_test("Boolean literals", """
        print(true)
        print(false)
    """, ["true", "false"])

    runner.run_test("Equality", """
        print(1 == 1)
        print(1 == 2)
    """, ["true", "false"])

    runner.run_test("Inequality", """
        print(1 != 2)
        print(1 != 1)
    """, ["true", "false"])

    runner.run_test("Less than / greater than", """
        print(1 < 2)
        print(2 > 1)
        print(1 >= 1)
        print(1 <= 0)
    """, ["true", "true", "true", "false"])

    runner.run_test("Logical AND", """
        print(true and true)
        print(true and false)
    """, ["true", "false"])

    runner.run_test("Logical OR", """
        print(false or true)
        print(false or false)
    """, ["true", "false"])

    runner.run_test("Logical NOT", """
        print(not true)
        print(not false)
    """, ["false", "true"])

    # ==================== If/Else ====================
    print("\n--- If/Else ---")

    runner.run_test("Simple if", """
        let x = 10
        if (x > 5) {
            print("big")
        }
    """, ["big"])

    runner.run_test("If-else", """
        let x = 3
        if (x > 5) {
            print("big")
        } else {
            print("small")
        }
    """, ["small"])

    runner.run_test("If-else if-else", """
        let x = 5
        if (x > 10) {
            print("large")
        } else if (x > 3) {
            print("medium")
        } else {
            print("small")
        }
    """, ["medium"])

    runner.run_test("Nested if", """
        let x = 10
        let y = 20
        if (x > 5) {
            if (y > 15) {
                print("both")
            }
        }
    """, ["both"])

    # ==================== While Loops ====================
    print("\n--- While Loops ---")

    runner.run_test("Simple while", """
        let i = 0
        let sum = 0
        while (i < 5) {
            sum = sum + i
            i = i + 1
        }
        print(sum)
    """, ["10"])

    runner.run_test("While with break", """
        let i = 0
        while (true) {
            if (i >= 3) {
                break
            }
            print(i)
            i = i + 1
        }
    """, ["0", "1", "2"])

    runner.run_test("While with continue", """
        let i = 0
        while (i < 5) {
            i = i + 1
            if (i == 3) {
                continue
            }
            print(i)
        }
    """, ["1", "2", "4", "5"])

    # ==================== For-In Loops ====================
    print("\n--- For-In Loops ---")

    runner.run_test("For-in with range", """
        for (i in range(5)) {
            print(i)
        }
    """, ["0", "1", "2", "3", "4"])

    runner.run_test("For-in with array", """
        let arr = [10, 20, 30]
        for (x in arr) {
            print(x)
        }
    """, ["10", "20", "30"])

    runner.run_test("For-in with range(start, end)", """
        for (i in range(2, 5)) {
            print(i)
        }
    """, ["2", "3", "4"])

    runner.run_test("Nested for loops", """
        let sum = 0
        for (i in range(3)) {
            for (j in range(3)) {
                sum = sum + 1
            }
        }
        print(sum)
    """, ["9"])

    # ==================== Arrays ====================
    print("\n--- Arrays ---")

    runner.run_test("Array literal", """
        let arr = [1, 2, 3]
        print(arr)
    """, ["[1, 2, 3]"])

    runner.run_test("Array index access", """
        let arr = [10, 20, 30]
        print(arr[0])
        print(arr[1])
        print(arr[2])
    """, ["10", "20", "30"])

    runner.run_test("Array index assignment", """
        let arr = [1, 2, 3]
        arr[1] = 99
        print(arr)
    """, ["[1, 99, 3]"])

    runner.run_test("Array push and pop", """
        let arr = [1, 2]
        push(arr, 3)
        print(arr)
        let last = pop(arr)
        print(last)
        print(arr)
    """, ["[1, 2, 3]", "3", "[1, 2]"])

    runner.run_test("Array length", """
        let arr = [1, 2, 3, 4, 5]
        print(len(arr))
    """, ["5"])

    # ==================== Functions ====================
    print("\n--- Functions ---")

    runner.run_test("Simple function", """
        fn add(a, b) {
            return a + b
        }
        print(add(3, 4))
    """, ["7"])

    runner.run_test("Function with no return value", """
        fn greet(name) {
            print("Hello, " + name)
        }
        greet("World")
    """, ["Hello, World"])

    runner.run_test("Recursive function (factorial)", """
        fn factorial(n) {
            if (n <= 1) {
                return 1
            }
            return n * factorial(n - 1)
        }
        print(factorial(5))
    """, ["120"])

    runner.run_test("Recursive function (fibonacci)", """
        fn fib(n) {
            if (n <= 1) {
                return n
            }
            return fib(n - 1) + fib(n - 2)
        }
        print(fib(10))
    """, ["55"])

    runner.run_test("Function with local variables", """
        fn square_sum(a, b) {
            let sa = a * a
            let sb = b * b
            return sa + sb
        }
        print(square_sum(3, 4))
    """, ["25"])

    runner.run_test("Multiple functions calling each other", """
        fn double(x) {
            return x * 2
        }
        fn triple(x) {
            return x * 3
        }
        fn process(x) {
            return double(x) + triple(x)
        }
        print(process(5))
    """, ["25"])

    runner.run_test("Function with array parameter", """
        fn sum_array(arr) {
            let total = 0
            for (x in arr) {
                total = total + x
            }
            return total
        }
        print(sum_array([1, 2, 3, 4, 5]))
    """, ["15"])

    # ==================== Built-in Functions ====================
    print("\n--- Built-in Functions ---")

    runner.run_test("abs()", """
        print(abs(-5))
        print(abs(5))
    """, ["5", "5"])

    runner.run_test("min() and max()", """
        print(min(3, 7))
        print(max(3, 7))
        print(min([5, 2, 8, 1]))
        print(max([5, 2, 8, 1]))
    """, ["3", "7", "1", "8"])

    runner.run_test("type()", """
        print(type(42))
        print(type(3.14))
        print(type("hello"))
        print(type(true))
        print(type([1, 2]))
    """, ["int", "float", "string", "bool", "array"])

    runner.run_test("str() conversion", """
        print(str(42) + " is the answer")
    """, ["42 is the answer"])

    runner.run_test("int() conversion", """
        print(int(3.7))
    """, ["3"])

    # ==================== Complex Programs ====================
    print("\n--- Complex Programs ---")

    runner.run_test("Bubble sort", """
        fn bubble_sort(arr) {
            let n = len(arr)
            for (i in range(n)) {
                for (j in range(0, n - 1 - i)) {
                    if (arr[j] > arr[j + 1]) {
                        let temp = arr[j]
                        arr[j] = arr[j + 1]
                        arr[j + 1] = temp
                    }
                }
            }
            return arr
        }
        let data = [5, 3, 8, 1, 9, 2, 7]
        print(bubble_sort(data))
    """, ["[1, 2, 3, 5, 7, 8, 9]"])

    runner.run_test("GCD (Euclidean algorithm)", """
        fn gcd(a, b) {
            while (b != 0) {
                let temp = b
                b = a % b
                a = temp
            }
            return a
        }
        print(gcd(48, 18))
        print(gcd(100, 75))
    """, ["6", "25"])

    runner.run_test("Prime number check", """
        fn is_prime(n) {
            if (n < 2) {
                return false
            }
            let i = 2
            while (i * i <= n) {
                if (n % i == 0) {
                    return false
                }
                i = i + 1
            }
            return true
        }
        
        # Find primes up to 20
        let primes = []
        for (n in range(2, 21)) {
            if (is_prime(n)) {
                push(primes, n)
            }
        }
        print(primes)
    """, ["[2, 3, 5, 7, 11, 13, 17, 19]"])

    runner.run_test("FizzBuzz (first 15)", """
        let result = []
        for (i in range(1, 16)) {
            if (i % 15 == 0) {
                push(result, "FizzBuzz")
            } else if (i % 3 == 0) {
                push(result, "Fizz")
            } else if (i % 5 == 0) {
                push(result, "Buzz")
            } else {
                push(result, i)
            }
        }
        for (item in result) {
            print(item)
        }
    """, ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz",
          "11", "Fizz", "13", "14", "FizzBuzz"])

    runner.run_test("Matrix multiplication (2x2)", """
        # Represent 2x2 matrix as flat array [a00, a01, a10, a11]
        fn mat_mul(a, b) {
            let c = [0, 0, 0, 0]
            c[0] = a[0] * b[0] + a[1] * b[2]
            c[1] = a[0] * b[1] + a[1] * b[3]
            c[2] = a[2] * b[0] + a[3] * b[2]
            c[3] = a[2] * b[1] + a[3] * b[3]
            return c
        }
        
        let a = [1, 2, 3, 4]
        let b = [5, 6, 7, 8]
        let c = mat_mul(a, b)
        print(c)
    """, ["[19, 22, 43, 50]"])

    # ==================== Error Handling ====================
    print("\n--- Error Handling ---")

    runner.run_error_test("Division by zero", """
        print(10 / 0)
    """, VMError)

    runner.run_error_test("Undefined variable", """
        print(x)
    """, VMError)

    runner.run_error_test("Array index out of bounds", """
        let arr = [1, 2, 3]
        print(arr[5])
    """, VMError)

    runner.run_error_test("Undefined function", """
        foo()
    """, VMError)

    runner.run_error_test("Wrong argument count", """
        fn add(a, b) { return a + b }
        add(1)
    """, VMError)

    runner.run_error_test("Unterminated string", '''
        print("hello)
    ''', LexerError)

    # ==================== Summary ====================
    success = runner.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
