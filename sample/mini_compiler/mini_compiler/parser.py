"""
Recursive Descent Parser for MiniLang.

Converts a stream of tokens (from the Lexer) into an Abstract Syntax Tree.
Supports: variable declarations, assignments, arithmetic, comparisons,
logical operators, if/else, while, for-in, functions, arrays, and print.
"""

from typing import List, Optional
from lexer import Token, TokenType
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


class ParseError(Exception):
    """Raised when the parser encounters a syntax error."""

    def __init__(self, message: str, token: Token):
        self.token = token
        super().__init__(
            f"ParseError at L{token.line}:C{token.column}: {message} "
            f"(got {token.type.name} = {token.value!r})"
        )


class Parser:
    """
    Recursive descent parser for MiniLang.

    Grammar (simplified):
        program     -> (statement | function_def)* EOF
        function_def -> 'fn' IDENT '(' params ')' block
        block       -> '{' statement* '}'
        statement   -> let_stmt | assign_stmt | if_stmt | while_stmt
                     | for_stmt | return_stmt | break_stmt | continue_stmt
                     | print_stmt | expr_stmt
        let_stmt    -> 'let' IDENT '=' expression
        if_stmt     -> 'if' '(' expression ')' block ('else' block)?
        while_stmt  -> 'while' '(' expression ')' block
        for_stmt    -> 'for' '(' IDENT 'in' expression ')' block
        expression  -> logic_or
        logic_or    -> logic_and ('or' logic_and)*
        logic_and   -> equality ('and' equality)*
        equality    -> comparison (('==' | '!=') comparison)*
        comparison  -> addition (('<' | '>' | '<=' | '>=') addition)*
        addition    -> multiplication (('+' | '-') multiplication)*
        multiplication -> unary (('*' | '/' | '%') unary)*
        unary       -> ('not' | '-') unary | postfix
        postfix     -> primary ( '(' args ')' | '[' expr ']' )*
        primary     -> INTEGER | FLOAT | STRING | BOOL | IDENT
                     | '(' expression ')' | '[' elements ']'
    """

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        tok = self._current()
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def _expect(self, token_type: TokenType) -> Token:
        tok = self._current()
        if tok.type != token_type:
            raise ParseError(f"Expected {token_type.name}", tok)
        return self._advance()

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._current().type in types:
            return self._advance()
        return None

    def _check(self, *types: TokenType) -> bool:
        return self._current().type in types

    # ---- Top-level ----

    def parse(self) -> Program:
        """Parse the entire program."""
        program = Program(line=1, column=1)
        while not self._check(TokenType.EOF):
            if self._check(TokenType.FN):
                program.statements.append(self._parse_function_def())
            else:
                program.statements.append(self._parse_statement())
        return program

    # ---- Function Definition ----

    def _parse_function_def(self) -> FunctionDef:
        tok = self._expect(TokenType.FN)
        name_tok = self._expect(TokenType.IDENTIFIER)
        self._expect(TokenType.LPAREN)

        params = []
        if not self._check(TokenType.RPAREN):
            params.append(self._expect(TokenType.IDENTIFIER).value)
            while self._match(TokenType.COMMA):
                params.append(self._expect(TokenType.IDENTIFIER).value)
        self._expect(TokenType.RPAREN)

        body = self._parse_block()
        return FunctionDef(
            name=name_tok.value, params=params, body=body,
            line=tok.line, column=tok.column
        )

    # ---- Block ----

    def _parse_block(self) -> Block:
        tok = self._expect(TokenType.LBRACE)
        stmts = []
        while not self._check(TokenType.RBRACE, TokenType.EOF):
            stmts.append(self._parse_statement())
        self._expect(TokenType.RBRACE)
        return Block(statements=stmts, line=tok.line, column=tok.column)

    # ---- Statements ----

    def _parse_statement(self) -> ASTNode:
        if self._check(TokenType.LET):
            return self._parse_let()
        elif self._check(TokenType.IF):
            return self._parse_if()
        elif self._check(TokenType.WHILE):
            return self._parse_while()
        elif self._check(TokenType.FOR):
            return self._parse_for()
        elif self._check(TokenType.RETURN):
            return self._parse_return()
        elif self._check(TokenType.BREAK):
            tok = self._advance()
            return BreakStatement(line=tok.line, column=tok.column)
        elif self._check(TokenType.CONTINUE):
            tok = self._advance()
            return ContinueStatement(line=tok.line, column=tok.column)
        elif self._check(TokenType.PRINT):
            return self._parse_print()
        else:
            return self._parse_expr_or_assign()

    def _parse_let(self) -> LetStatement:
        tok = self._expect(TokenType.LET)
        name_tok = self._expect(TokenType.IDENTIFIER)
        self._expect(TokenType.ASSIGN)
        value = self._parse_expression()
        return LetStatement(
            name=name_tok.value, value=value,
            line=tok.line, column=tok.column
        )

    def _parse_if(self) -> IfStatement:
        tok = self._expect(TokenType.IF)
        self._expect(TokenType.LPAREN)
        condition = self._parse_expression()
        self._expect(TokenType.RPAREN)
        then_block = self._parse_block()

        else_block = None
        if self._match(TokenType.ELSE):
            if self._check(TokenType.IF):
                # else if -> wrap in a block containing a single if statement
                inner_if = self._parse_if()
                else_block = Block(
                    statements=[inner_if],
                    line=inner_if.line, column=inner_if.column
                )
            else:
                else_block = self._parse_block()

        return IfStatement(
            condition=condition, then_block=then_block, else_block=else_block,
            line=tok.line, column=tok.column
        )

    def _parse_while(self) -> WhileStatement:
        tok = self._expect(TokenType.WHILE)
        self._expect(TokenType.LPAREN)
        condition = self._parse_expression()
        self._expect(TokenType.RPAREN)
        body = self._parse_block()
        return WhileStatement(
            condition=condition, body=body,
            line=tok.line, column=tok.column
        )

    def _parse_for(self) -> ForStatement:
        tok = self._expect(TokenType.FOR)
        self._expect(TokenType.LPAREN)
        var_tok = self._expect(TokenType.IDENTIFIER)
        self._expect(TokenType.IN)
        iterable = self._parse_expression()
        self._expect(TokenType.RPAREN)
        body = self._parse_block()
        return ForStatement(
            var_name=var_tok.value, iterable=iterable, body=body,
            line=tok.line, column=tok.column
        )

    def _parse_return(self) -> ReturnStatement:
        tok = self._expect(TokenType.RETURN)
        value = None
        if not self._check(TokenType.RBRACE, TokenType.EOF):
            # Check if the next token could start an expression
            if not self._check(TokenType.LET, TokenType.IF, TokenType.WHILE,
                               TokenType.FOR, TokenType.FN, TokenType.PRINT,
                               TokenType.BREAK, TokenType.CONTINUE, TokenType.RETURN):
                value = self._parse_expression()
        return ReturnStatement(value=value, line=tok.line, column=tok.column)

    def _parse_print(self) -> PrintStatement:
        tok = self._expect(TokenType.PRINT)
        self._expect(TokenType.LPAREN)
        expr = self._parse_expression()
        self._expect(TokenType.RPAREN)
        return PrintStatement(expression=expr, line=tok.line, column=tok.column)

    def _parse_expr_or_assign(self) -> ASTNode:
        """Parse an expression statement, or an assignment if '=' follows."""
        expr = self._parse_expression()

        if self._match(TokenType.ASSIGN):
            value = self._parse_expression()
            if isinstance(expr, Identifier):
                return AssignStatement(
                    name=expr.name, value=value,
                    line=expr.line, column=expr.column
                )
            elif isinstance(expr, IndexAccess):
                return IndexAssignStatement(
                    obj=expr.obj, index=expr.index, value=value,
                    line=expr.line, column=expr.column
                )
            else:
                raise ParseError("Invalid assignment target", self._current())

        return ExpressionStatement(
            expression=expr, line=expr.line, column=expr.column
        )

    # ---- Expressions (precedence climbing) ----

    def _parse_expression(self) -> ASTNode:
        return self._parse_logic_or()

    def _parse_logic_or(self) -> ASTNode:
        left = self._parse_logic_and()
        while self._match(TokenType.OR):
            right = self._parse_logic_and()
            left = LogicalOp(op="or", left=left, right=right,
                             line=left.line, column=left.column)
        return left

    def _parse_logic_and(self) -> ASTNode:
        left = self._parse_equality()
        while self._match(TokenType.AND):
            right = self._parse_equality()
            left = LogicalOp(op="and", left=left, right=right,
                             line=left.line, column=left.column)
        return left

    def _parse_equality(self) -> ASTNode:
        left = self._parse_comparison()
        while True:
            tok = self._match(TokenType.EQ, TokenType.NEQ)
            if tok is None:
                break
            right = self._parse_comparison()
            left = ComparisonOp(op=tok.value, left=left, right=right,
                                line=left.line, column=left.column)
        return left

    def _parse_comparison(self) -> ASTNode:
        left = self._parse_addition()
        while True:
            tok = self._match(TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE)
            if tok is None:
                break
            right = self._parse_addition()
            left = ComparisonOp(op=tok.value, left=left, right=right,
                                line=left.line, column=left.column)
        return left

    def _parse_addition(self) -> ASTNode:
        left = self._parse_multiplication()
        while True:
            tok = self._match(TokenType.PLUS, TokenType.MINUS)
            if tok is None:
                break
            right = self._parse_multiplication()
            left = BinaryOp(op=tok.value, left=left, right=right,
                            line=left.line, column=left.column)
        return left

    def _parse_multiplication(self) -> ASTNode:
        left = self._parse_unary()
        while True:
            tok = self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT)
            if tok is None:
                break
            right = self._parse_unary()
            left = BinaryOp(op=tok.value, left=left, right=right,
                            line=left.line, column=left.column)
        return left

    def _parse_unary(self) -> ASTNode:
        if self._check(TokenType.NOT):
            tok = self._advance()
            operand = self._parse_unary()
            return UnaryOp(op="not", operand=operand,
                           line=tok.line, column=tok.column)
        if self._check(TokenType.MINUS):
            tok = self._advance()
            operand = self._parse_unary()
            return UnaryOp(op="-", operand=operand,
                           line=tok.line, column=tok.column)
        return self._parse_postfix()

    def _parse_postfix(self) -> ASTNode:
        """Parse postfix operations: function calls and index access."""
        node = self._parse_primary()
        while True:
            if self._check(TokenType.LPAREN):
                # Function call
                self._advance()
                args = []
                if not self._check(TokenType.RPAREN):
                    args.append(self._parse_expression())
                    while self._match(TokenType.COMMA):
                        args.append(self._parse_expression())
                self._expect(TokenType.RPAREN)
                if isinstance(node, Identifier):
                    node = FunctionCall(
                        name=node.name, arguments=args,
                        line=node.line, column=node.column
                    )
                else:
                    raise ParseError("Expected function name before '('", self._current())
            elif self._check(TokenType.LBRACKET):
                # Index access
                self._advance()
                index = self._parse_expression()
                self._expect(TokenType.RBRACKET)
                node = IndexAccess(
                    obj=node, index=index,
                    line=node.line, column=node.column
                )
            else:
                break
        return node

    def _parse_primary(self) -> ASTNode:
        tok = self._current()

        if tok.type == TokenType.INTEGER:
            self._advance()
            return IntegerLiteral(value=tok.value, line=tok.line, column=tok.column)

        if tok.type == TokenType.FLOAT:
            self._advance()
            return FloatLiteral(value=tok.value, line=tok.line, column=tok.column)

        if tok.type == TokenType.STRING:
            self._advance()
            return StringLiteral(value=tok.value, line=tok.line, column=tok.column)

        if tok.type in (TokenType.TRUE, TokenType.FALSE):
            self._advance()
            return BooleanLiteral(value=tok.value, line=tok.line, column=tok.column)

        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            return Identifier(name=tok.value, line=tok.line, column=tok.column)

        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        if tok.type == TokenType.LBRACKET:
            return self._parse_array_literal()

        raise ParseError("Unexpected token", tok)

    def _parse_array_literal(self) -> ArrayLiteral:
        tok = self._expect(TokenType.LBRACKET)
        elements = []
        if not self._check(TokenType.RBRACKET):
            elements.append(self._parse_expression())
            while self._match(TokenType.COMMA):
                elements.append(self._parse_expression())
        self._expect(TokenType.RBRACKET)
        return ArrayLiteral(elements=elements, line=tok.line, column=tok.column)
