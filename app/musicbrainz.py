import logging
import threading
import time
from typing import Any

import requests

from app.config import MB_USER_AGENT
from app.types import MBCandidate, MBCandidateDetail, TrackDetail

log = logging.getLogger(__name__)

MB_API = "https://musicbrainz.org/ws/2"
_last_request_ts: float = 0.0
_rate_lock = threading.Lock()

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BACKOFF = [5, 15, 30]  # seconds between attempts


def _get(url: str, params: dict[str, Any] | None = None) -> requests.Response:
    """Rate-limited GET with retry on transient network/server errors."""
    global _last_request_ts
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        if attempt:
            delay = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
            log.warning("MB request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt, _MAX_RETRIES, delay, last_exc)
            time.sleep(delay)
        with _rate_lock:
            elapsed = time.time() - _last_request_ts
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            _last_request_ts = time.time()
        try:
            resp = requests.get(
                url, params=params,
                headers={"User-Agent": MB_USER_AGENT},
                timeout=30,  # raised from 15s to handle slow MB responses
            )
            if resp.status_code in _TRANSIENT_STATUS:
                last_exc = requests.HTTPError(response=resp)
                continue
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            continue
    raise last_exc  # type: ignore[misc]


def _parse_candidate(release: dict[str, Any]) -> MBCandidate:
    """Extract an MBCandidate from a raw MusicBrainz release dict."""
    artist_credit: list[dict[str, Any]] = release.get("artist-credit", [])
    artist = artist_credit[0]["artist"]["name"] if artist_credit else ""
    label_info: list[dict[str, Any]] = release.get("label-info", [])
    label = label_info[0]["label"]["name"] if label_info and label_info[0].get("label") else ""
    tracks: list[str] = []
    media = release.get("media", [])
    for medium in media:
        for t in medium.get("tracks", []):
            tracks.append(t["title"])
    # Search results omit track listings but include track-count per medium
    track_count = len(tracks) if tracks else sum(m.get("track-count", 0) for m in media)
    return MBCandidate(
        id=release.get("id", ""),
        title=release.get("title", ""),
        artist=artist,
        year=(release.get("date", "") or "")[:4],
        country=release.get("country", ""),
        label=label,
        score=release.get("score", 0),
        tracks=tracks,
        track_count=track_count,
        disambiguation=release.get("disambiguation", ""),
    )




def _escape_lucene(s: str) -> str:
    """Escape double-quotes inside a Lucene quoted phrase."""
    return s.replace('"', '\\"')


def _build_query(query: str, artist: str, title: str) -> str:
    """Return a MusicBrainz Lucene query string.

    When *artist* and/or *title* are given, construct a field-specific query so
    that MB's relevance scoring does not conflate artist-name matches with
    album-title matches (e.g. searching "etta james at last" as a plain query
    floods results with self-titled "Etta James" albums because "etta james"
    appears in *both* the artist and title fields of those releases).

    Falls back to the raw *query* string when no structured fields are provided,
    preserving existing plain-text search behaviour.
    """
    parts: list[str] = []
    if artist:
        parts.append(f'artist:"{_escape_lucene(artist)}"')
    if title:
        parts.append(f'release:"{_escape_lucene(title)}"')
    if parts:
        return " AND ".join(parts)
    return query


def search_releases(query: str, *, artist: str = "", title: str = "") -> list[MBCandidate]:
    """Search MB releases; returns up to 25 candidates sorted by relevance."""
    q = _build_query(query, artist, title)
    resp = _get(f"{MB_API}/release", params={"query": q, "fmt": "json", "limit": 25})
    releases: list[dict[str, Any]] = resp.json().get("releases", [])
    return [_parse_candidate(r) for r in releases]


def get_release_by_id(mb_uuid: str) -> MBCandidateDetail:
    """Fetch full release detail including track listing and label from MB."""
    resp = _get(
        f"{MB_API}/release/{mb_uuid}",
        params={"inc": "recordings+labels+artist-credits", "fmt": "json"},
    )
    data: dict[str, Any] = resp.json()
    base = _parse_candidate(data)
    detailed_tracks: list[TrackDetail] = []
    for medium in data.get("media", []):
        for t in medium.get("tracks", []):
            detailed_tracks.append(
                TrackDetail(
                    position=t.get("position", 0),
                    title=t.get("title", ""),
                    length_ms=t.get("length"),
                )
            )
    return MBCandidateDetail(
        id=base["id"],
        title=base["title"],
        artist=base["artist"],
        year=base["year"],
        country=base["country"],
        label=base["label"],
        score=base["score"],
        tracks=detailed_tracks,
        track_count=base["track_count"],
        disambiguation=base["disambiguation"],
    )
