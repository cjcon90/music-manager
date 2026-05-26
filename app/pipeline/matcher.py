import re

from app.musicbrainz import get_release_by_id, search_releases
from app.pipeline.probe import ProbeResult

MATCH_THRESHOLD = 0.70

# Suffixes that appear in filenames/CUE sheets but not in MusicBrainz release titles.
# Stripped before searching so Japanese pressings, remasters, etc. still match.
_NOISE = re.compile(
    r"\s*[\[(]?"
    r"(?:SHM-?CD|SACD|HDCD|XRCD|UHQCD|MQA"
    r"|(?:Super\s+)?Hi(?:gh)?[\s-]?Res(?:olution)?"
    r"|Remaster(?:ed)?(?:\s+\d{4})?"
    r"|\d{4}\s+Remaster(?:ed)?"
    r"|Deluxe(?:\s+Edition)?"
    r"|Expanded(?:\s+Edition)?"
    r"|Special(?:\s+Edition)?"
    r"|(?:\d+(?:th|st|nd|rd)\s+)?Anniversary(?:\s+Edition)?"
    r"|Bonus\s+Tracks?"
    r"|Japan(?:ese)?(?:\s+Edition)?"
    r")[\])]?.*$",
    re.IGNORECASE,
)

# Ripper-added pressing/format annotations — never appear in canonical MB titles.
# CUE sheets from EAC/dBpoweramp commonly embed these:
#   {UK, Sterling}  {Original UK}  {EU}  {UK, Sterling LH}
#   (LP)  (2LP)  (EP)  (CD)  [LP]
#   (UK version)  (US pressing)  (original version)
_PRESSING = re.compile(
    r"\s*\{[^}]+\}"                                             # {UK, Sterling} {EU} etc.
    r"|\s*[\[(]\s*\d*\s*(?:LP|EP|CD|7\"|12\")\s*[\])]"         # (LP) (2LP) [CD] etc.
    r"|\s*[\[(][^\])]*\b(?:version|pressing)\b[^\])]*[\])]",    # (UK version) (US pressing) etc.
    re.IGNORECASE,
)


def normalise_title(s: str) -> str:
    s = re.sub(r"^\d+[\s._\-]+", "", s)
    return re.sub(r"[^\w]", "", s).lower()


def clean_album(album: str) -> str:
    """Strip edition/format noise so MB searches hit the canonical release title."""
    album = _PRESSING.sub("", album)
    return _NOISE.sub("", album).strip()


def track_title_score(local: list[str], mb: list[str]) -> float:
    if not mb:
        return 0.0
    local_norm = [normalise_title(t) for t in local]
    matched = sum(1 for mb_t in mb if any(normalise_title(mb_t) in l for l in local_norm))
    return matched / len(mb)


def find_best_release(probe: ProbeResult) -> str | None:
    if not probe.artist and not probe.album:
        return None

    artist = probe.artist.replace('"', "")
    album = clean_album(probe.album).replace('"', "")
    query = f'artist:"{artist}" AND release:"{album}"'
    candidates = search_releases(query)

    # Allow up to 3 extra local tracks (bonus/Japan-only) vs the MB release,
    # but reject if MB has more than 1 track we don't have.
    candidates = [
        c for c in candidates
        if c["track_count"] <= probe.track_count + 1
        and probe.track_count <= c["track_count"] + 3
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:3]

    best_id: str | None = None
    best_score = 0.0

    for c in top:
        try:
            detail = get_release_by_id(c["id"])
        except Exception:
            continue
        mb_titles = [t["title"] for t in detail["tracks"]]
        score = track_title_score(probe.track_titles, mb_titles)
        if score > best_score:
            best_score = score
            best_id = c["id"]

    return best_id if best_score >= MATCH_THRESHOLD else None
