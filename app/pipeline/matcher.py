import re

from app.musicbrainz import get_release_by_id, search_releases
from app.pipeline.probe import ProbeResult

MATCH_THRESHOLD = 0.70

# Ripper-added pressing/format annotations — never appear in canonical MB titles.
# CUE sheets from EAC/dBpoweramp commonly embed these:
#   {UK, Sterling}  {Original UK}  {EU}
#   (LP)  (2LP)  (EP)  (CD)  [LP]
#   (UK version)  (US pressing)
_PRESSING = re.compile(
    r"\s*\{[^}]+\}"                                             # {UK, Sterling} {EU} etc.
    r"|\s*[\[(]\s*\d*\s*(?:LP|EP|CD|7\"|12\")\s*[\])]"         # (LP) (2LP) [CD] etc.
    r"|\s*[\[(][^\])]*\b(?:version|pressing)\b[^\])]*[\])]",    # (UK version) (US pressing) etc.
    re.IGNORECASE,
)


def normalise_title(s: str) -> str:
    """Strip leading track numbers and non-word characters for fuzzy comparison."""
    s = re.sub(r"^\d+[\s._\-]+", "", s)
    return re.sub(r"[^\w]", "", s).lower()


def clean_album(album: str) -> str:
    """Strip format/pressing annotations that never appear in MB titles."""
    return _PRESSING.sub("", album).strip()


def _strip_all_noise(album: str) -> str:
    """Aggressively strip all parenthetical/bracketed content and disc position suffixes.

    Handles cases clean_album misses:
      'Tommy (1 of 2)'                       → 'Tommy'
      'Tommy 2 of 2'                         → 'Tommy'
      'Quadrophenia (1991 MFSL Gold) - Disc 1' → 'Quadrophenia'
      'The Who Sell Out (1970 UK Reissue)'   → 'The Who Sell Out'
      'Who's Next (Remastered)'              → "Who's Next"
      '1999'                                 → '1999'  (no brackets — unchanged)
    """
    result = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]", "", album)  # strip (), [], {}
    result = re.sub(r"\s+\d+\s+of\s+\d+\s*$", "", result)          # strip bare "2 of 2"
    result = re.sub(
        r"\s*[-–]\s*(?:disc|disk|cd)\s*\d+.*$", "", result, flags=re.IGNORECASE
    )  # strip "- Disc 1" suffixes
    return result.strip("-– ").strip()


def _album_search_variants(album: str) -> list[str]:
    """Return de-duplicated album title variants to try, from conservative to aggressive.

    Tier 1: strip format/pressing annotations only (e.g. {UK, Sterling}, (LP))
    Tier 2: strip all bracketed content + disc suffixes (handles edition info, years, etc.)
    Tier 3: first two words of tier-2 result (last resort for heavily decorated titles)
    """
    tier1 = clean_album(album)
    tier2 = _strip_all_noise(album)
    words = tier2.split()
    tier3 = " ".join(words[:2]) if len(words) > 2 else ""

    seen: set[str] = set()
    variants: list[str] = []
    for v in [tier1, tier2, tier3]:
        if v and v not in seen:
            seen.add(v)
            variants.append(v)
    return variants


def track_title_score(local: list[str], mb: list[str]) -> float:
    """Fraction of MB track titles that fuzzily match at least one local track title."""
    if not mb:
        return 0.0
    local_norm = [normalise_title(t) for t in local]
    matched = sum(1 for mb_t in mb if any(normalise_title(mb_t) in l for l in local_norm))
    return matched / len(mb)


def _attempt_search(artist: str, album: str, probe: ProbeResult) -> str | None:
    """Run one MB search for (artist, album) and return the best UUID or None."""
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


def find_best_release(probe: ProbeResult) -> str | None:
    """Search MusicBrainz for the best matching release; return its UUID or None.

    Tries progressively more aggressive title cleaning until a match is found:
      1. Strip format/pressing annotations only
      2. Strip all bracketed content and disc suffixes
      3. Search with just the first two words of the album title
    """
    if not probe.artist and not probe.album:
        return None

    artist = probe.artist.replace('"', "")

    for album_variant in _album_search_variants(probe.album):
        album = album_variant.replace('"', "")
        result = _attempt_search(artist, album, probe)
        if result is not None:
            return result

    return None
