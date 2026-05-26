"""
Lucene-flavoured search parser for the host/object quick-search box.

Accepts boolean expressions with AND/OR/NOT keywords (case-insensitive)
and parentheses. Each leaf is either a bare term (matched against
`hostname`, any `labels.*` value, and any `inventory.*` value) or a
`field:value` pair. `hostname:foo` targets the hostname column; any
other field name is looked up under both `labels.<field>` and
`inventory.<field>`, and `labels.x:y` / `inventory.x:y` route
explicitly.

Values are treated as MongoDB regex (case-insensitive). A trailing
or embedded `*` is translated to `.*` and `?` to `.` so common Lucene
wildcards behave intuitively; quoted values (`"foo bar"`) are escaped
literally so spaces survive tokenisation.
"""
import re


class SearchSyntaxError(ValueError):
    """User-facing parser error — raised with a short, displayable message."""


_TOKEN_RE = re.compile(
    r'''
    \s+
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<colon>:)
    | (?P<bang>!)
    | (?P<quoted>"(?:[^"\\]|\\.)*")
    | (?P<word>[^\s():!"]+)
    ''',
    re.VERBOSE,
)

_KEYWORDS = {'AND': 'AND', 'OR': 'OR', 'NOT': 'NOT'}


def _tokenize(text):
    """Yield (kind, value) tuples; raises SearchSyntaxError on unterminated quotes."""
    tokens = []
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            # The only way to get here is an unterminated quote — `_TOKEN_RE`
            # already consumes whitespace and every non-quote character.
            raise SearchSyntaxError(
                f"Unterminated quote near position {pos}"
            )
        pos = match.end()
        if match.group('lparen'):
            tokens.append(('LPAREN', '('))
        elif match.group('rparen'):
            tokens.append(('RPAREN', ')'))
        elif match.group('colon'):
            tokens.append(('COLON', ':'))
        elif match.group('bang'):
            tokens.append(('NOT', '!'))
        elif match.group('quoted'):
            raw = match.group('quoted')
            tokens.append(('QUOTED', raw[1:-1].replace('\\"', '"')))
        elif match.group('word'):
            word = match.group('word')
            upper = word.upper()
            if upper in _KEYWORDS:
                tokens.append((_KEYWORDS[upper], word))
            else:
                tokens.append(('WORD', word))
        # whitespace match groups: nothing emitted
    return tokens


class _Parser:  # pylint: disable=too-few-public-methods
    """Recursive-descent parser; entry point is `parse()`."""

    def __init__(self, tokens):
        self._tokens = tokens
        self._pos = 0

    def _peek(self):
        return self._tokens[self._pos] if self._pos < len(self._tokens) else (None, None)

    def _consume(self):
        token = self._peek()
        self._pos += 1
        return token

    def parse(self):
        """Parse the full token stream and return the resulting AST."""
        node = self._parse_or()
        if self._pos != len(self._tokens):
            kind, value = self._peek()
            raise SearchSyntaxError(
                f"Unexpected token {value!r} (kind={kind}) at position {self._pos}"
            )
        return node

    def _parse_or(self):
        children = [self._parse_and()]
        while self._peek()[0] == 'OR':
            self._consume()
            children.append(self._parse_and())
        if len(children) == 1:
            return children[0]
        return ('OR', children)

    def _parse_and(self):
        children = [self._parse_unary()]
        while True:
            kind = self._peek()[0]
            if kind == 'AND':
                self._consume()
                children.append(self._parse_unary())
            elif kind in ('WORD', 'QUOTED', 'LPAREN', 'NOT'):
                # implicit AND between adjacent atoms
                children.append(self._parse_unary())
            else:
                break
        if len(children) == 1:
            return children[0]
        return ('AND', children)

    def _parse_unary(self):
        if self._peek()[0] == 'NOT':
            self._consume()
            return ('NOT', self._parse_unary())
        return self._parse_atom()

    def _parse_atom(self):
        kind, value = self._peek()
        if kind == 'LPAREN':
            self._consume()
            inner = self._parse_or()
            close_kind, _ = self._peek()
            if close_kind != 'RPAREN':
                raise SearchSyntaxError("Missing closing parenthesis ')'")
            self._consume()
            return inner
        if kind in ('WORD', 'QUOTED'):
            return self._parse_term()
        if kind is None:
            raise SearchSyntaxError("Unexpected end of expression")
        raise SearchSyntaxError(f"Unexpected token {value!r}")

    def _parse_term(self):
        kind, value = self._consume()
        # field:value when first token is a bare word and next is COLON
        if kind == 'WORD' and self._peek()[0] == 'COLON':
            self._consume()  # eat ':'
            val_kind, val_value = self._peek()
            if val_kind in ('WORD', 'QUOTED'):
                self._consume()
                return ('TERM', value, val_value, val_kind == 'QUOTED')
            raise SearchSyntaxError(
                f"Expected value after '{value}:' but got {val_value!r}"
            )
        return ('TERM', None, value, kind == 'QUOTED')


_FIELD_KEY_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def _value_to_regex(value, quoted):
    """
    Turn the user-typed value into a Mongo regex string. Quoted values
    are escaped verbatim (so `"foo*"` matches literal `foo*`). Unquoted
    values support Lucene-style `*` (→`.*`) and `?` (→`.`); the rest is
    treated as regex and falls back to a literal escape if it doesn't
    compile.
    """
    if quoted:
        return re.escape(value)

    converted = []
    for char in value:
        if char == '*':
            converted.append('.*')
        elif char == '?':
            converted.append('.')
        else:
            converted.append(char)
    regex_str = ''.join(converted)
    try:
        re.compile(regex_str)
    except re.error:
        return re.escape(value)
    return regex_str


def _dict_match_expr(field_name, regex_str, target):
    """
    `$expr` that regex-matches either the key (`target='k'`) or the
    string-coerced value (`target='v'`) of every entry in a dict-typed
    field. We need this `$expr`/`$objectToArray` dance because Mongo
    has no direct "any-key matches regex" predicate on dynamic-document
    fields, and `labels.<exact-key>` only works when we know the key.
    """
    if target == 'v':
        input_expr = {
            '$convert': {
                'input': f'$$kv.{target}',
                'to': 'string',
                'onError': '',
                'onNull': '',
            },
        }
    else:
        input_expr = f'$$kv.{target}'
    return {'$expr': {
        '$anyElementTrue': {
            '$map': {
                'input': {'$objectToArray': {
                    '$ifNull': [f'${field_name}', {}],
                }},
                'as': 'kv',
                'in': {
                    '$regexMatch': {
                        'input': input_expr,
                        'regex': regex_str,
                        'options': 'i',
                    },
                },
            },
        },
    }}


def _leaf_to_mongo(field, value, quoted):
    """Translate a single TERM into a Mongo predicate dict."""
    regex_str = _value_to_regex(value, quoted)
    # Keys are matched as full strings — `basti_test` does NOT match a
    # label called `basti_test2`. Wildcards (`*`, `?`) expand the
    # anchored regex so users can opt in to prefix/suffix matching with
    # `basti_test*`. Values stay unanchored (substring match) because
    # that's how users have always searched in the Syncer.
    key_regex_str = f'^{regex_str}$'

    if field is None:
        return {'$or': [
            {'hostname': {'$regex': regex_str, '$options': 'i'}},
            _dict_match_expr('labels', key_regex_str, 'k'),
            _dict_match_expr('labels', regex_str, 'v'),
            _dict_match_expr('inventory', key_regex_str, 'k'),
            _dict_match_expr('inventory', regex_str, 'v'),
        ]}

    if not _FIELD_KEY_RE.fullmatch(field):
        raise SearchSyntaxError(f"Invalid field name {field!r}")

    if field == 'hostname':
        return {'hostname': {'$regex': regex_str, '$options': 'i'}}

    if field.startswith('labels.') or field.startswith('inventory.'):
        return {field: {'$regex': regex_str, '$options': 'i'}}

    return {'$or': [
        {f'labels.{field}': {'$regex': regex_str, '$options': 'i'}},
        {f'inventory.{field}': {'$regex': regex_str, '$options': 'i'}},
    ]}


def _ast_to_mongo(node):
    op = node[0]
    if op == 'TERM':
        _, field, value, quoted = node
        return _leaf_to_mongo(field, value, quoted)
    if op == 'AND':
        return {'$and': [_ast_to_mongo(child) for child in node[1]]}
    if op == 'OR':
        return {'$or': [_ast_to_mongo(child) for child in node[1]]}
    if op == 'NOT':
        return {'$nor': [_ast_to_mongo(node[1])]}
    raise SearchSyntaxError(f"Internal: unknown AST node {op!r}")


def parse_search(text):
    """
    Parse the user-typed search expression and return a MongoDB
    `__raw__` filter dict. Returns None for an empty expression.
    Raises SearchSyntaxError on any malformed input — callers are
    expected to surface the message and fall back to an empty result.
    """
    text = (text or '').strip()
    if not text:
        return None
    tokens = _tokenize(text)
    if not tokens:
        return None
    ast = _Parser(tokens).parse()
    return _ast_to_mongo(ast)
