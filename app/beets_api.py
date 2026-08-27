from contextlib import contextmanager
from typing import Any, Generator

from beets.library import Library

from app.config import BEETS_DB_PATH
from app.types import AlbumInfo, TrackInfo

# beets query matching albums with no MusicBrainz release ID. `field::regex`
# is beets' regex form; ^$ matches the empty string beets stores for an
# unmatched album. Composes with a free-text search by whitespace-joining.
NO_MBID_QUERY = "mb_albumid::^$"


@contextmanager
def _library() -> Generator[Library, None, None]:
    """Context manager: open and close the beets Library for a single operation."""
    lib = Library(BEETS_DB_PATH)
    try:
        yield lib
    finally:
        lib._close()


def _album_to_info(a: Any) -> AlbumInfo:
    """Convert a beets Album object to an AlbumInfo TypedDict."""
    items = list(a.items())
    first_item = items[0] if items else None

    first_path: str | None = None
    if first_item:
        p = first_item.path
        if isinstance(p, bytes):
            p = p.decode("utf-8", errors="replace")
        first_path = p

    artpath: str | None = None
    if a.artpath:
        ap = a.artpath
        if isinstance(ap, bytes):
            ap = ap.decode("utf-8", errors="replace")
        artpath = ap

    return AlbumInfo(
        id=a.id,
        album=a.album or "",
        artist=a.albumartist or "",
        year=a.year,
        tracks=len(items),
        path=first_path,
        artpath=artpath,
        mb_albumid=a.mb_albumid or "",
        format=first_item.format if first_item else "",
    )


def count_albums() -> int:
    with _library() as lib:
        return len(list(lib.albums()))


def count_albums_without_mbid() -> int:
    with _library() as lib:
        return len(list(lib.albums(NO_MBID_QUERY)))


def list_albums(query: str = "") -> list[AlbumInfo]:
    with _library() as lib:
        result = [_album_to_info(a) for a in lib.albums(query)]
    result.sort(key=lambda x: (x["artist"].lower(), x["album"].lower()))
    return result


def get_album_by_id(album_id: int) -> AlbumInfo | None:
    with _library() as lib:
        albums = list(lib.albums(f"id:{album_id}"))
    if not albums:
        return None
    return _album_to_info(albums[0])


def get_album_tracks(album_id: int) -> list[TrackInfo]:
    result: list[TrackInfo] = []
    with _library() as lib:
        for i in lib.items(f"album_id:{album_id}"):
            path: str = i.path
            if isinstance(path, bytes):
                path = path.decode("utf-8", errors="replace")
            result.append(TrackInfo(track=i.track or 0, title=i.title or "", path=path))
    return sorted(result, key=lambda x: x["track"])
