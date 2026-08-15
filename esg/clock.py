"""
Time, in one place.

datetime.utcnow() is deprecated from Python 3.12 and returns a naive value
that silently misrepresents itself as local time in some libraries. Everything
here stores naive-UTC deliberately (the DateTime columns are timezone-less),
so the conversion happens once, here, rather than being re-derived per module.

Tests patch now() to control time.
"""

from datetime import datetime, timezone

_override = None


def now():
    """Current UTC instant as a naive datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today():
    return now().date()


def freeze(instant):
    """Test hook — pin now() to a fixed instant. Pass None to release."""
    global _override
    _override = instant
