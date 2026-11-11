"""Injectable clock. Use clock.now() everywhere, never datetime.now()."""
from datetime import datetime, timedelta, timezone

_offset = timedelta(0)
_frozen: datetime | None = None


def now() -> datetime:
    """Naive UTC time plus any demo offset."""
    if _frozen is not None:
        return _frozen
    return datetime.now(timezone.utc).replace(tzinfo=None) + _offset


def advance(hours: float) -> datetime:
    """Move the clock forward (demo bar: +3h, +24h, +48h)."""
    global _offset, _frozen
    if _frozen is not None:
        _frozen = _frozen + timedelta(hours=hours)
    else:
        _offset += timedelta(hours=hours)
    return now()


def freeze(at: datetime) -> None:
    """For tests: pin the clock."""
    global _frozen
    _frozen = at


def reset() -> None:
    global _offset, _frozen
    _offset = timedelta(0)
    _frozen = None
