"""
The timezone the web UI shows its timestamps in.

The syncer stores every timestamp in UTC and keeps doing so — that is
what makes the cleanup jobs, the API and two servers in different
countries agree with each other. Only the presentation is local: the
browser is the one place that knows where the user sits, so a small
script in the page layout writes its timezone into the ``syncer_tz``
cookie and this module turns that back into a ``tzinfo``.

The cookie carries both the IANA name and the current UTC offset
(``Europe/Berlin|-120``). The name is the accurate one — it knows about
daylight saving time, so a timestamp from January is converted with
January's offset. It needs a timezone database on the server; where
that is missing, the offset is used instead, which is right for
everything but the other side of a DST switch.

Until the first page has set the cookie — and for anything that runs
outside a request, like the CLI — the fallback is UTC, i.e. exactly the
behaviour this module replaced.
"""
import datetime
import re
from zoneinfo import ZoneInfo

from flask import has_request_context, request

TZ_COOKIE = 'syncer_tz'
UTC = datetime.timezone.utc

# The cookie reads `Europe/Berlin|-120`. Both halves are validated
# before use — a cookie is user input like any other. The name pattern
# has no '.' in it, so it cannot walk out of the zoneinfo directory.
_NAME_RE = re.compile(r'^[A-Za-z0-9_+/-]{1,64}$')
_OFFSET_RE = re.compile(r'^-?\d{1,4}$')
# getTimezoneOffset() is the minutes to ADD to local time to get UTC, so
# it is the negative of the offset a tzinfo carries. UTC-12 … UTC+14.
_MIN_OFFSET = -14 * 60
_MAX_OFFSET = 12 * 60


def _timezone_from_cookie(value):
    """Turn a `syncer_tz` cookie value into a tzinfo, or None."""
    if not value or len(value) > 80:
        return None
    name, _, offset = value.partition('|')
    if _NAME_RE.fullmatch(name):
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError, OSError):
            # Unknown zone, or no timezone database on this machine —
            # the offset below still gives the user their own clock.
            pass
    if _OFFSET_RE.fullmatch(offset):
        minutes = int(offset)
        if _MIN_OFFSET <= minutes <= _MAX_OFFSET:
            return datetime.timezone(datetime.timedelta(minutes=-minutes))
    return None


def user_timezone():
    """
    The timezone of the browser this request came from, UTC when it is
    not known. Never raises — a wrong clock must not take a page down.
    """
    try:
        if not has_request_context():
            return UTC
        return _timezone_from_cookie(request.cookies.get(TZ_COOKIE)) or UTC
    except Exception:  # pylint: disable=broad-exception-caught
        return UTC


def to_local(value, tzinfo=None):
    """
    Move a stored timestamp into the user's timezone. A naive value is
    read as UTC, which is how the syncer writes them. Anything that is
    not a datetime is handed back untouched so the callers can stay
    simple.
    """
    if not isinstance(value, datetime.datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(tzinfo or user_timezone())


def format_local(value, fmt='%Y-%m-%d %H:%M:%S'):
    """
    Render a stored timestamp in the user's timezone. Registered as the
    ``localtime`` Jinja filter, so a template writes
    ``{{ job.last_start|localtime('%Y-%m-%d %H:%M') }}``.
    """
    local = to_local(value)
    if not isinstance(local, datetime.datetime):
        return '' if value is None else str(value)
    return local.strftime(fmt)
