"""Preserve RSS publication times; never replace missing dates with collection time."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re


JST = timezone(timedelta(hours=9))


def _raw_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    # RFC dates sometimes use JST, which email.utils does not recognize.
    raw = re.sub(r"\sJST$", " +0900", raw, flags=re.IGNORECASE)
    try:
        result = parsedate_to_datetime(raw)
    except (ValueError, TypeError, OverflowError):
        try:
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            return None
    # A missing offset cannot safely be interpreted in the collector's local zone.
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    try:
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _parsed_timestamp(value):
    if not isinstance(value, (tuple, list)) or len(value) < 6:
        return None
    try:
        # feedparser's *_parsed structures are normalized to UTC.
        return datetime(*value[:6], tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def publication_time(entry):
    """Return an aware UTC published/updated time, or None if neither is valid."""
    for field in ("published", "updated"):
        raw = entry.get(field)
        result = _raw_timestamp(raw)
        if result is None and not raw:
            result = _parsed_timestamp(entry.get(field + "_parsed"))
        if result is not None:
            return result
    return None


def publication_time_jst(entry):
    result = publication_time(entry)
    return result.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S") if result else None
