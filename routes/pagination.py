"""Opaque offset cursors for paginated list routes."""
import base64
import binascii
import json

from fastapi import HTTPException

MAX_CURSOR_OFFSET = 10_000


def _invalid() -> HTTPException:
    return HTTPException(status_code=400, detail="Invalid pagination cursor.")


def encode_cursor(offset: int) -> str:
    """Encodes a list offset as an opaque, URL-safe cursor."""
    raw = json.dumps({"o": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> int:
    """Decodes a cursor from encode_cursor; raises HTTP 400 for anything malformed or out of range."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeError):
        raise _invalid() from None
    if not isinstance(data, dict):
        raise _invalid()
    offset = data.get("o")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= MAX_CURSOR_OFFSET:
        raise _invalid()
    return offset


def paginate(results: list, offset: int, page: int) -> tuple:
    """Slices one page out of results fetched with limit=offset+page+1; returns (items, next_cursor)."""
    items = results[offset:offset + page]
    next_cursor = encode_cursor(offset + page) if len(results) > offset + page else None
    return items, next_cursor
