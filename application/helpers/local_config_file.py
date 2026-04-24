"""
Read & write `local_config.py` as a safe key/value store.

The file is a plain Python module but it is never executed by this
helper — everything is parsed with `ast` and evaluated with
`ast.literal_eval`, so a malformed / hostile file cannot run code
through this path. Callers work with a flat `dict[str, primitive]`
view of the `config = {...}` assignment.

Design goals:

- **Preserve everything except the dict literal** — shebang, docstring,
  imports, and any non-`config` statements stay in place. We find the
  source-offset span of the `config = {...}` value and splice a new
  literal in.
- **Atomic on disk** — write to a sibling tempfile and `os.replace`,
  so a crash mid-write cannot leave a partial file.
- **Safe values only** — values must be primitive (str / int / float /
  bool / None). `set_key` rejects anything else rather than quietly
  serialising something unexpected.
"""
import ast
import logging
import os
import pprint

log = logging.getLogger(__name__)


_ALLOWED_VALUE_TYPES = (str, int, float, bool, type(None))


class LocalConfigError(Exception):
    """Raised on any read/write error the caller should surface."""


# ---------------------------------------------------------------- read


def load(path):
    """
    Return the `config` dict currently stored in `path` as a plain
    Python dict. Missing file → empty dict. Parse errors raise
    `LocalConfigError` so the caller can show the reason instead of a
    silent empty state (the admin UI needs that visibility).
    """
    try:
        source = _read(path)
    except FileNotFoundError:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError as exp:
        raise LocalConfigError(
            f"local_config.py has a SyntaxError on line {exp.lineno}: {exp.msg}"
        ) from exp
    node = _find_config_assignment(tree)
    if node is None:
        return {}
    try:
        value = ast.literal_eval(node.value)
    except (ValueError, SyntaxError) as exp:
        raise LocalConfigError(
            "local_config.py `config` value is not a plain literal "
            f"(contains expressions / variables): {exp}"
        ) from exp
    if not isinstance(value, dict):
        raise LocalConfigError(
            f"local_config.py `config` is {type(value).__name__}, not a dict"
        )
    return value


# ---------------------------------------------------------------- write


def set_key(path, key, value):
    """
    Add or update `key` → `value` in `config`. Writes the file atomically.
    Returns the merged dict.

    Raises `LocalConfigError` for invalid keys / values so the admin view
    can render the reason in a flash.
    """
    _validate_key(key)
    _validate_value(value)
    current = load(path)
    current[key] = value
    _persist(path, current)
    return current


def delete_key(path, key):
    """Remove `key` if present. Returns the merged dict."""
    _validate_key(key)
    current = load(path)
    current.pop(key, None)
    _persist(path, current)
    return current


def replace_all(path, new_dict):
    """
    Overwrite `config` with `new_dict` verbatim. Validates every key
    and value before touching disk.
    """
    for key, value in new_dict.items():
        _validate_key(key)
        _validate_value(value)
    _persist(path, dict(new_dict))
    return new_dict


# ---------------------------------------------------------------- internals


_KEY_MAX = 128


def _validate_key(key):
    if not isinstance(key, str):
        raise LocalConfigError(f"Key must be a string, got {type(key).__name__}")
    stripped = key.strip()
    if not stripped:
        raise LocalConfigError("Key must not be empty")
    if len(stripped) > _KEY_MAX:
        raise LocalConfigError(f"Key longer than {_KEY_MAX} characters")
    # Python-identifier-ish: letters/digits/underscore. We don't require
    # a *valid* identifier because Flask config keys can technically be
    # anything — but we do refuse whitespace, quotes and separators so
    # the dict literal stays parseable.
    for char in stripped:
        if not (char.isalnum() or char in '_-.'):
            raise LocalConfigError(
                f"Key contains forbidden character {char!r}; "
                f"allowed: letters, digits, underscore, hyphen, dot"
            )


def _validate_value(value):
    if isinstance(value, _ALLOWED_VALUE_TYPES):
        return
    raise LocalConfigError(
        f"Value type {type(value).__name__} is not allowed here — only "
        f"str / int / float / bool / None. Edit the file by hand if you "
        f"need a list or nested dict."
    )


def _persist(path, dict_value):
    new_literal = _format_dict_literal(dict_value)

    try:
        source = _read(path)
    except FileNotFoundError:
        source = (
            "#!/usr/bin/env python3\n"
            '"""\nLocal Config File\n"""\n'
            "# Only Update from here inside the config = {} object\n\n"
            f"config = {new_literal}\n"
        )
        _atomic_write(path, source)
        return

    try:
        tree = ast.parse(source)
    except SyntaxError as exp:
        raise LocalConfigError(
            f"Cannot rewrite local_config.py — existing file does not "
            f"parse (line {exp.lineno}: {exp.msg}). Fix it on disk first."
        ) from exp

    node = _find_config_assignment(tree)
    if node is None:
        trailing = '' if source.endswith('\n') else '\n'
        new_source = source + f"{trailing}\nconfig = {new_literal}\n"
        _atomic_write(path, new_source)
        return

    offsets = _line_offsets(source)
    start = offsets[node.value.lineno - 1] + node.value.col_offset
    end = offsets[node.value.end_lineno - 1] + node.value.end_col_offset
    new_source = source[:start] + new_literal + source[end:]
    _atomic_write(path, new_source)


def _find_config_assignment(tree):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == 'config':
            return node
    return None


def _line_offsets(source):
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _format_dict_literal(value):
    return pprint.pformat(value, width=100, sort_dicts=True, indent=1)


def _read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _atomic_write(path, content):
    """
    Replace `path` with `content` as safely as the filesystem permissions allow.

    Preferred path: sibling tempfile + ``os.replace`` — crash-safe, but needs
    write access on the parent directory. Common deployments only grant write
    access on ``local_config.py`` itself (not on ``/srv``), so fall back to an
    in-place truncate+write on the existing file when the directory isn't
    writable. The in-place path drops atomicity but avoids forcing operators
    to widen permissions on the app root just so the admin UI can edit one
    file.
    """
    directory = os.path.dirname(path) or '.'
    if os.access(directory, os.W_OK):
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                fh.write(content)
            os.replace(tmp, path)
            return
        except OSError as exp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if not isinstance(exp, PermissionError):
                raise LocalConfigError(f"Cannot write {path}: {exp}") from exp
            # Directory looked writable but the rename was refused (e.g. the
            # file itself is read-only or owned by another user). Fall through
            # to the in-place attempt so the operator gets the file-level
            # error message instead of a confusing directory hint.

    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(content)
    except PermissionError as exp:
        raise LocalConfigError(
            f"Cannot write {path}: {exp.strerror}. "
            f"Grant the syncer OS user write access on the file itself "
            f"(e.g. `chown uwsgi:uwsgi {path}` or `chmod u+w {path}`) — "
            f"{directory!r} does not need to be writable."
        ) from exp
    except OSError as exp:
        raise LocalConfigError(f"Cannot write {path}: {exp}") from exp


def is_writable(path):
    """
    True if the current process can update `path` at all — either via the
    preferred atomic tempfile+rename (needs directory write access) or via
    an in-place rewrite of an existing file (needs only file write access).
    """
    directory = os.path.dirname(path) or '.'
    if os.access(directory, os.W_OK):
        return True
    return os.path.isfile(path) and os.access(path, os.W_OK)
