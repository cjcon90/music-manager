from typing import NotRequired, TypedDict


class AlbumInfo(TypedDict):
    id: int
    album: str
    artist: str
    year: int
    tracks: int
    path: str | None
    artpath: str | None
    mb_albumid: str
    format: str


class TrackInfo(TypedDict):
    track: int
    title: str
    path: str


class TrackDetail(TypedDict):
    position: int
    title: str
    length_ms: NotRequired[int | None]


class TrackRow(TypedDict):
    local: str | None
    mb: str | None
    status: str  # 'match' | 'diff' | 'missing' | 'extra'
    mb_pos: int | None


class FailedEntry(TypedDict):
    ts: str
    path: str
    name: str
    kind: str  # 'nomatch' | 'skipped' | 'error'
    line: str  # full original log line, used as dismiss key


class QueuedPath(TypedDict):
    name: str
    path: str
    mtime: float


class ActiveImport(TypedDict):
    path: str
    since: float


class MBCandidate(TypedDict):
    id: str
    title: str
    artist: str
    year: str
    country: str
    label: str
    score: int
    tracks: list[str]
    track_count: int
    disambiguation: str
    score_label: NotRequired[str]
    track_rows: NotRequired[list[TrackRow]]


class MBCandidateDetail(TypedDict):
    id: str
    title: str
    artist: str
    year: str
    country: str
    label: str
    score: int
    tracks: list[TrackDetail]
    track_count: int
    disambiguation: str


class WishlistEntry(TypedDict):
    mb_id: str
    title: str
    artist: str
    year: str
    added_at: str  # ISO datetime string
