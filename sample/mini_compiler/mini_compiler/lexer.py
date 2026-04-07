"""
Lexer (Tokenizer) for MiniLang.

Converts raw source text into a stream of Token objects.
Supported token types: numbers, strings, identifiers, keywords,
operators, delimiters, and special symbols.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List


class TokenType(Enum):
    # Literals
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    BOOLEAN = auto()

    # Identifiers & Keywords
    IDENTIFIER = auto()
    LET = auto()
    FN = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    IN = auto()
    RETURN = auto()
    PRINT = auto()
    TRUE = auto()
    FALSE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    BREAK = auto()
    CONTINUE = auto()

    # Operators
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # *
    SLASH = auto()       # /
    PERCENT = auto()     # %
    ASSIGN = auto()      # =
    EQ = auto()          # ==
    NEQ = auto()         # !=
    LT = auto()          # <
    GT = auto()          # >
    LTE = auto()         # <=
    GTE = auto()         # >=

    # Delimiters
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    COMMA = auto()       # ,
    SEMICOLON = auto()   # ;
    COLON = auto()       # :
    DOT = auto()         # .
    ARROW = auto()       # ->

    # Special
    EOF = auto()
    NEWLINE = auto()


KEYWORDS = {
    "let": TokenType.LET,
    "fn": TokenType.FN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "return": TokenType.RETURN,
    "print": TokenType.PRINT,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
}


@dataclass
class Token:
    type: TokenType
    value: object
    line: int
    column: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:C{self.column})"


class LexerError(Exception):
    """Raised when the lexer encounters an invalid character or sequence."""

    def __init__(self, message: str, line: int, column: int):
        self.line = line
        self.column = column
        super().__init__(f"LexerError at L{line}:C{column}: {message}")


class Lexer:
    """
    Tokenizes MiniLang source code.

    Usage:
        lexer = Lexer(source_code)
        tokens = lexer.tokenize()
    """

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []

    def _current(self) -> str:
        if self.pos < len(self.source):
            return self.source[self.pos]
        return "\0"

    def _peek(self, offset: int = 1) -> str:
        idx = self.pos + offset
        if idx < len(self.source):
            return self.source[idx]
        return "\0"

    def _advance(self) -> str:
        ch = self._current()
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _add_token(self, token_type: TokenType, value: object = None):
        self.tokens.append(Token(token_type, value, self.line, self.column))

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self._current()
            if ch in (" ", "\t", "\r"):
                self._advance()
            elif ch == "\n":
                self._advance()
            elif ch == "#":
                # Single-line comment: skip until end of line
                while self.pos < len(self.source) and self._current() != "\n":
                    self._advance()
            elif ch == "/" and self._peek() == "/":
                # C-style single-line comment
                while self.pos < len(self.source) and self._current() != "\n":
                    self._advance()
            else:
                break

    def _read_string(self, quote_char: str) -> str:
        """Read a string literal enclosed in quote_char."""
        self._advance()  # skip opening quote
        result = []
        while self.pos < len(self.source):
            ch = self._current()
            if ch == "\\":
                self._advance()
                escaped = self._current()
                escape_map = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}
                if escaped in escape_map:
                    result.append(escape_map[escaped])
                else:
                    result.append("\\" + escaped)
                self._advance()
            elif ch == quote_char:
                self._advance()  # skip closing quote
                return "".join(result)
            elif ch == "\n":
                raise LexerError("Unterminated string literal", self.line, self.column)
            else:
                result.append(ch)
                self._advance()
        raise LexerError("Unterminated string literal", self.line, self.column)

    def _read_number(self) -> Token:
        """Read an integer or float literal."""
        start_line = self.line
        start_col = self.column
        num_str = []
        is_float = False

        while self.pos < len(self.source) and (self._current().isdigit() or self._current() == "."):
            if self._current() == ".":
                if is_float:
                    break  # second dot -> stop
                # Check if next char is a digit (otherwise it's a method call dot)
                if not self._peek().isdigit():
                    break
                is_float = True
            num_str.append(self._advance())

        value_str = "".join(num_str)
        if is_float:
            return Token(TokenType.FLOAT, float(value_str), start_line, start_col)
        else:
            return Token(TokenType.INTEGER, int(value_str), start_line, start_col)

    def _read_identifier(self) -> Token:
        """Read an identifier or keyword."""
        start_line = self.line
        start_col = self.column
        chars = []
        while self.pos < len(self.source) and (self._current().isalnum() or self._current() == "_"):
            chars.append(self._advance())
        word = "".join(chars)

        # Check if it's a keyword
        if word in KEYWORDS:
            token_type = KEYWORDS[word]
            value = word
            if token_type == TokenType.TRUE:
                value = True
            elif token_type == TokenType.FALSE:
                value = False
            return Token(token_type, value, start_line, start_col)
        else:
            return Token(TokenType.IDENTIFIER, word, start_line, start_col)

    def tokenize(self) -> List[Token]:
        """Tokenize the entire source and return a list of tokens."""
        while self.pos < len(self.source):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break

            start_line = self.line
            start_col = self.column
            ch = self._current()

            # String literals
            if ch in ('"', "'"):
                string_val = self._read_string(ch)
                self.tokens.append(Token(TokenType.STRING, string_val, start_line, start_col))

            # Numbers
            elif ch.isdigit():
                self.tokens.append(self._read_number())

            # Identifiers / Keywords
            elif ch.isalpha() or ch == "_":
                self.tokens.append(self._read_identifier())

            # Two-character operators
            elif ch == "=" and self._peek() == "=":
                self._advance(); self._advance()
                self.tokens.append(Token(TokenType.EQ, "==", start_line, start_col))
            elif ch == "!" and self._peek() == "=":
                self._advance(); self._advance()
                self.tokens.append(Token(TokenType.NEQ, "!=", start_line, start_col))
            elif ch == "<" and self._peek() == "=":
                self._advance(); self._advance()
                self.tokens.append(Token(TokenType.LTE, "<=", start_line, start_col))
            elif ch == ">" and self._peek() == "=":
                self._advance(); self._advance()
                self.tokens.append(Token(TokenType.GTE, ">=", start_line, start_col))
            elif ch == "-" and self._peek() == ">":
                self._advance(); self._advance()
                self.tokens.append(Token(TokenType.ARROW, "->", start_line, start_col))

            # Single-character operators and delimiters
            elif ch == "+":
                self._advance()
                self.tokens.append(Token(TokenType.PLUS, "+", start_line, start_col))
            elif ch == "-":
                self._advance()
                self.tokens.append(Token(TokenType.MINUS, "-", start_line, start_col))
            elif ch == "*":
                self._advance()
                self.tokens.append(Token(TokenType.STAR, "*", start_line, start_col))
            elif ch == "/":
                self._advance()
                self.tokens.append(Token(TokenType.SLASH, "/", start_line, start_col))
            elif ch == "%":
                self._advance()
                self.tokens.append(Token(TokenType.PERCENT, "%", start_line, start_col))
            elif ch == "=":
                self._advance()
                self.tokens.append(Token(TokenType.ASSIGN, "=", start_line, start_col))
            elif ch == "<":
                self._advance()
                self.tokens.append(Token(TokenType.LT, "<", start_line, start_col))
            elif ch == ">":
                self._advance()
                self.tokens.append(Token(TokenType.GT, ">", start_line, start_col))
            elif ch == "(":
                self._advance()
                self.tokens.append(Token(TokenType.LPAREN, "(", start_line, start_col))
            elif ch == ")":
                self._advance()
                self.tokens.append(Token(TokenType.RPAREN, ")", start_line, start_col))
            elif ch == "{":
                self._advance()
                self.tokens.append(Token(TokenType.LBRACE, "{", start_line, start_col))
            elif ch == "}":
                self._advance()
                self.tokens.append(Token(TokenType.RBRACE, "}", start_line, start_col))
            elif ch == "[":
                self._advance()
                self.tokens.append(Token(TokenType.LBRACKET, "[", start_line, start_col))
            elif ch == "]":
                self._advance()
                self.tokens.append(Token(TokenType.RBRACKET, "]", start_line, start_col))
            elif ch == ",":
                self._advance()
                self.tokens.append(Token(TokenType.COMMA, ",", start_line, start_col))
            elif ch == ";":
                self._advance()
                self.tokens.append(Token(TokenType.SEMICOLON, ";", start_line, start_col))
            elif ch == ":":
                self._advance()
                self.tokens.append(Token(TokenType.COLON, ":", start_line, start_col))
            elif ch == ".":
                self._advance()
                self.tokens.append(Token(TokenType.DOT, ".", start_line, start_col))
            else:
                raise LexerError(f"Unexpected character: {ch!r}", self.line, self.column)

        self.tokens.append(Token(TokenType.EOF, None, self.line, self.column))
        return self.tokens
