from contextlib import contextmanager
from typing import Any, Generator

from beets.library import Library

from app.config import BEETS_DB_PATH
from app.types import AlbumInfo, TrackInfo

# beets query matching albums with no MusicBrainz release ID. `field::regex`
# is beets' regex form; ^$ matches the empty string beets stores for an
# unmatched album. Composes with a free-text search by whitespace-joining.
NO_MBID_QUERY = "mb_albumid::^$"

# Track count, first track's path and format for every album, in one query.
#
# The obvious `for a in albums: a.items()` costs one query per album — 959 of
# them, 1.3s of the library page's render time, to read three values. SQLite
# guarantees that when a query has a single MIN()/MAX() aggregate, the bare
# columns (`path`, `format`) come from the row that produced it, so ordering by
# disc-then-track picks the same first track beets' own default sort would.
_ITEM_AGG_SQL = """
SELECT album_id,
       COUNT(*),
       MIN(COALESCE(disc, 0) * 100000 + COALESCE(track, 0)),
       path,
       format
FROM items
{where}
GROUP BY album_id
"""


@contextmanager
def _library() -> Generator[Library, None, None]:
    """Context manager: open and close the beets Library for a single operation."""
    lib = Library(BEETS_DB_PATH)
    try:
        yield lib
    finally:
        lib._close()


def _item_aggregates(lib: Any, album_id: int | None = None) -> dict[int, tuple[int, Any, str]]:
    """Map album_id -> (track_count, first_path, first_format).

    Restricted to one album when *album_id* is given, so the single-album
    callers don't scan the whole items table.
    """
    sql: str
    args: tuple[int, ...]
    if album_id is None:
        sql, args = _ITEM_AGG_SQL.format(where=""), ()
    else:
        sql, args = _ITEM_AGG_SQL.format(where="WHERE album_id = ?"), (album_id,)
    with lib.transaction() as tx:
        rows = tx.query(sql, args)
    return {row[0]: (row[1], row[3], row[4]) for row in rows}


def _decode(value: Any) -> str | None:
    """beets stores paths as bytes; templates and JSON need str."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _album_to_info(a: Any, agg: dict[int, tuple[int, Any, str]]) -> AlbumInfo:
    """Convert a beets Album object to an AlbumInfo TypedDict.

    *agg* supplies the per-album item data; an album missing from it simply has
    no tracks on disk.
    """
    track_count, first_path, fmt = agg.get(a.id, (0, None, ""))

    return AlbumInfo(
        id=a.id,
        album=a.album or "",
        artist=a.albumartist or "",
        year=a.year,
        tracks=track_count,
        path=_decode(first_path),
        artpath=_decode(a.artpath) if a.artpath else None,
        mb_albumid=a.mb_albumid or "",
        format=fmt or "",
    )


def count_albums() -> int:
    with _library() as lib:
        return len(list(lib.albums()))


def count_albums_without_mbid() -> int:
    with _library() as lib:
        return len(list(lib.albums(NO_MBID_QUERY)))


def list_albums(query: str = "") -> list[AlbumInfo]:
    with _library() as lib:
        albums = list(lib.albums(query))
        agg = _item_aggregates(lib)
        result = [_album_to_info(a, agg) for a in albums]
    result.sort(key=lambda x: (x["artist"].lower(), x["album"].lower()))
    return result


def get_album_by_id(album_id: int) -> AlbumInfo | None:
    with _library() as lib:
        albums = list(lib.albums(f"id:{album_id}"))
        if not albums:
            return None
        return _album_to_info(albums[0], _item_aggregates(lib, album_id))


def get_album_tracks(album_id: int) -> list[TrackInfo]:
    result: list[TrackInfo] = []
    with _library() as lib:
        for i in lib.items(f"album_id:{album_id}"):
            result.append(
                TrackInfo(track=i.track or 0, title=i.title or "", path=_decode(i.path) or "")
            )
    return sorted(result, key=lambda x: x["track"])

