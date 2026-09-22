"""
Lucene-flavoured search parser for the host/object quick-search box.

Accepts boolean expressions with AND/OR/NOT keywords (case-insensitive)
and parentheses. Each leaf is either a bare term (matched against
`hostname`, any `labels.*` value, and any `inventory.*` value) or a
`field:value` pair. `hostname:foo` targets the hostname column; any
other field name is looked up under both `labels.<field>` and
`inventory.<field>`, and `labels.x:y` / `inventory.x:y` route
explicitly. Short forms save typing: `h:` for `hostname:`, `l.x:` for
`labels.x:` and `i.x:` for `inventory.x:`.

Values are treated as MongoDB regex (case-insensitive). A trailing
or embedded `*` is translated to `.*` and `?` to `.` so common Lucene
wildcards behave intuitively; quoted values (`"foo bar"`) are escaped
literally so spaces survive tokenisation. A value written between
slashes (`h:/^web\\d+$/`) is taken as a regular expression as-is — no
wildcard translation — for the cases where globbing is not enough.

`created:` is the one field that is not matched as a regex: it takes a
date (`today`, `yesterday` or `YYYY-MM-DD`), optionally prefixed with
`>=`, `>`, `<=` or `<`, and selects the hosts whose creation timestamp
falls in that day or range. The day is read in the timezone the caller
passes — the browser's, so `created:today` is the user's day — and
converted to the UTC the timestamps are stored in.
"""
import datetime
import re

from bson import ObjectId


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
    | (?P<regex>/(?:[^/\\]|\\.)*/(?=\s|\)|$))
    | (?P<word>[^\s():!"]+)
    ''',
    re.VERBOSE,
)

_KEYWORDS = {'AND': 'AND', 'OR': 'OR', 'NOT': 'NOT'}

# How the value of a term is turned into a regex, per token kind.
_VALUE_MODES = {'WORD': 'plain', 'QUOTED': 'quoted', 'REGEX': 'regex'}

# Short forms for the field prefix, so the common searches stay short.
_FIELD_ALIASES = {
    'h': 'hostname',
    'host': 'hostname',
    'created': 'create_time',
    'created_at': 'create_time',
}
_FIELD_PREFIX_ALIASES = (
    ('l.', 'labels.'),
    ('i.', 'inventory.'),
)


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
        elif match.group('regex'):
            # Only a token that starts with '/' and whose closing '/' ends
            # the token is a regex — 'srv/data' stays an ordinary word.
            raw = match.group('regex')
            tokens.append(('REGEX', raw[1:-1].replace('\\/', '/')))
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
            elif kind in ('WORD', 'QUOTED', 'REGEX', 'LPAREN', 'NOT'):
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
        if kind in ('WORD', 'QUOTED', 'REGEX'):
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
            if val_kind in _VALUE_MODES:
                self._consume()
                return ('TERM', value, val_value, _VALUE_MODES[val_kind])
            raise SearchSyntaxError(
                f"Expected value after '{value}:' but got {val_value!r}"
            )
        return ('TERM', None, value, _VALUE_MODES[kind])


_FIELD_KEY_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def _resolve_field(field):
    """
    Expand the short field forms: `h:` → `hostname:`, `l.env:` →
    `labels.env:`, `i.cpu:` → `inventory.cpu:`. Anything else is
    returned unchanged.
    """
    lowered = field.lower()
    if lowered in _FIELD_ALIASES:
        return _FIELD_ALIASES[lowered]
    for short, full in _FIELD_PREFIX_ALIASES:
        if lowered.startswith(short):
            return full + field[len(short):]
    return field


def _value_to_regex(value, mode):
    """
    Turn the user-typed value into a Mongo regex string. Quoted values
    are escaped verbatim (so `"foo*"` matches literal `foo*`). Slashed
    values (`/^web\\d+$/`) are taken as a regular expression as typed —
    an invalid one is an error instead of a silent literal match, since
    asking for a regex explicitly means a typo should be visible.
    Everything else supports Lucene-style `*` (→`.*`) and `?` (→`.`);
    the rest is treated as regex and falls back to a literal escape if
    it doesn't compile.
    """
    if mode == 'quoted':
        return re.escape(value)

    if mode == 'regex':
        try:
            re.compile(value)
        except re.error as error:
            raise SearchSyntaxError(
                f"Invalid regular expression /{value}/: {error}") from error
        return value

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


_DATE_TERM_RE = re.compile(r'^(?P<operator>>=|<=|>|<)?\s*(?P<date>\S+)$')
_ISO_DATE_RE = re.compile(r'^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$')

# operator -> (lower bound, upper bound) picked from (day start, next day)
_DATE_BOUNDS = {
    None: ('start', 'next'),
    '>=': ('start', None),
    '>':  ('next', None),
    '<=': (None, 'next'),
    '<':  (None, 'start'),
}


def _parse_date(text, tzinfo):
    """
    Turn `today`, `yesterday` or `YYYY-MM-DD` into the day it names in
    the user's timezone. Everything else is a syntax error — a date
    field silently matching nothing would look like "no host was
    created then".
    """
    lowered = text.strip().lower()
    if lowered == 'today':
        return datetime.datetime.now(tzinfo).date()
    if lowered == 'yesterday':
        return datetime.datetime.now(tzinfo).date() - datetime.timedelta(days=1)
    match = _ISO_DATE_RE.fullmatch(lowered)
    if match:
        try:
            return datetime.date(int(match.group('year')),
                                 int(match.group('month')),
                                 int(match.group('day')))
        except ValueError as error:
            raise SearchSyntaxError(f"{text!r} is not a valid date: {error}") from error
    raise SearchSyntaxError(
        f"{text!r} is not a date — use today, yesterday or YYYY-MM-DD")


def _range_condition(field, lower, upper):
    """`{field: {'$gte': lower, '$lt': upper}}` with the open ends left out."""
    bounds = {}
    if lower is not None:
        bounds['$gte'] = lower
    if upper is not None:
        bounds['$lt'] = upper
    return {field: bounds}


def _to_naive_utc(value):
    """
    The UTC instant a timezone-aware value names, as the naive datetime
    the syncer stores its timestamps as.
    """
    return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _created_to_mongo(value, mode, tzinfo):
    """
    Translate `created:<date>` into a Mongo predicate on the creation
    time of the host.

    The day is the user's local day — `created:today` asks about the
    date on their wall clock — while `create_time` is stored in UTC, so
    the two local midnights are converted before they are compared.

    Hosts that carry no `create_time` (everything created before the
    syncer wrote that field) are answered by the generation time of
    their Mongo `_id`: the moment the document was written, which is
    the same event, and covered by the `_id` index. Both branches are
    combined so one search answers for the whole database.
    """
    if mode == 'regex':
        raise SearchSyntaxError(
            "created: takes a date (today, yesterday, YYYY-MM-DD), not a regex")
    match = _DATE_TERM_RE.fullmatch(value.strip())
    if not match:
        raise SearchSyntaxError(f"Expected a date after 'created:', got {value!r}")
    day = _parse_date(match.group('date'), tzinfo)
    local_midnight = datetime.datetime(day.year, day.month, day.day, tzinfo=tzinfo)
    edges = {
        # Adding a day to the aware value moves to the next local
        # midnight, so a day that a DST switch makes 23 or 25 hours long
        # is still exactly that one day.
        'start': _to_naive_utc(local_midnight),
        'next': _to_naive_utc(local_midnight + datetime.timedelta(days=1)),
    }
    lower_name, upper_name = _DATE_BOUNDS[match.group('operator')]
    lower = edges[lower_name] if lower_name else None
    upper = edges[upper_name] if upper_name else None
    # `{'create_time': None}` matches both a missing field and an
    # explicit null, which is exactly the set the _id fallback answers.
    return {'$or': [
        _range_condition('create_time', lower, upper),
        {'$and': [
            {'create_time': None},
            _range_condition(
                '_id',
                ObjectId.from_datetime(lower) if lower else None,
                ObjectId.from_datetime(upper) if upper else None),
        ]},
    ]}


def _leaf_to_mongo(field, value, mode, tzinfo):
    """Translate a single TERM into a Mongo predicate dict."""
    if field is not None:
        if not _FIELD_KEY_RE.fullmatch(field):
            raise SearchSyntaxError(f"Invalid field name {field!r}")
        field = _resolve_field(field)
        # Resolved before the value is turned into a regex: a date field
        # reads its value as a date, not as a pattern.
        if field == 'create_time':
            return _created_to_mongo(value, mode, tzinfo)

    regex_str = _value_to_regex(value, mode)
    # Keys are matched as full strings — `basti_test` does NOT match a
    # label called `basti_test2`. Wildcards (`*`, `?`) expand the
    # anchored regex so users can opt in to prefix/suffix matching with
    # `basti_test*`. Values stay unanchored (substring match) because
    # that's how users have always searched in the Syncer. The group
    # keeps an alternation (`/web|db/`) from swallowing the anchors.
    key_regex_str = f'^(?:{regex_str})$'

    if field is None:
        return {'$or': [
            {'hostname': {'$regex': regex_str, '$options': 'i'}},
            _dict_match_expr('labels', key_regex_str, 'k'),
            _dict_match_expr('labels', regex_str, 'v'),
            _dict_match_expr('inventory', key_regex_str, 'k'),
            _dict_match_expr('inventory', regex_str, 'v'),
        ]}

    if field == 'hostname':
        return {'hostname': {'$regex': regex_str, '$options': 'i'}}

    if field.startswith('labels.') or field.startswith('inventory.'):
        return {field: {'$regex': regex_str, '$options': 'i'}}

    return {'$or': [
        {f'labels.{field}': {'$regex': regex_str, '$options': 'i'}},
        {f'inventory.{field}': {'$regex': regex_str, '$options': 'i'}},
    ]}


def _ast_to_mongo(node, tzinfo):
    op = node[0]
    if op == 'TERM':
        _, field, value, mode = node
        return _leaf_to_mongo(field, value, mode, tzinfo)
    if op == 'AND':
        return {'$and': [_ast_to_mongo(child, tzinfo) for child in node[1]]}
    if op == 'OR':
        return {'$or': [_ast_to_mongo(child, tzinfo) for child in node[1]]}
    if op == 'NOT':
        return {'$nor': [_ast_to_mongo(node[1], tzinfo)]}
    raise SearchSyntaxError(f"Internal: unknown AST node {op!r}")


def parse_search(text, tzinfo=None):
    """
    Parse the user-typed search expression and return a MongoDB
    `__raw__` filter dict. Returns None for an empty expression.
    Raises SearchSyntaxError on any malformed input — callers are
    expected to surface the message and fall back to an empty result.

    `tzinfo` is the timezone the dates of a `created:` term are read in
    — the user's, so `created:today` means their day. It defaults to
    UTC, which is what the stored timestamps use and therefore the
    right answer for anything that runs without a browser.
    """
    text = (text or '').strip()
    if not text:
        return None
    tokens = _tokenize(text)
    if not tokens:
        return None
    ast = _Parser(tokens).parse()
    return _ast_to_mongo(ast, tzinfo or datetime.timezone.utc)
