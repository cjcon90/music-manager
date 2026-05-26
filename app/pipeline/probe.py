import re
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.flac import FLAC

from app.pipeline import AUDIO_EXTS

# Written-out disc number words for CUE titles like "Disc One", "Disc Two".
_DISC_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass
class ProbeResult:
    artist: str = ""
    album: str = ""
    year: str = ""
    track_count: int = 0
    track_titles: list[str] = field(default_factory=list)
    timings: list[float] | None = None
    source_file: Path | None = None
    disc_number: int | None = None
    # Explicit CUE TRACK numbers — set by probe_multi_file_cue() so that
    # split_cue_rip() uses globally-correct track numbers (e.g. 7–12 for
    # Side B) rather than resetting to 1 for each section.
    track_numbers: list[int] | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProbeResult):
            return NotImplemented
        return (
            self.artist == other.artist
            and self.album == other.album
            and self.year == other.year
            and self.track_count == other.track_count
            and self.track_titles == other.track_titles
        )


def probe_cue(dirpath: Path) -> ProbeResult:
    cue_files = sorted(dirpath.glob("*.cue")) + sorted(dirpath.glob("*.CUE"))
    if not cue_files:
        return ProbeResult()
    non_isrc = [f for f in cue_files if "isrc" not in f.name.lower()]
    cue_path = non_isrc[0] if non_isrc else cue_files[0]
    return _parse_cue(cue_path, dirpath)


def probe_cue_file(dirpath: Path, cue_path: Path) -> ProbeResult:
    """Probe a specific CUE file rather than auto-detecting in the directory."""
    return _parse_cue(cue_path, dirpath)


def probe_flac(dirpath: Path) -> ProbeResult:
    files = sorted(f for f in dirpath.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS)
    if not files:
        return ProbeResult()

    artist = ""
    album = ""
    year = ""
    titles: list[str] = []

    for f in files:
        if f.suffix.lower() != ".flac":
            titles.append(f.stem)
            continue
        try:
            tags = FLAC(str(f))
            if not artist:
                artist = (tags.get("albumartist") or tags.get("artist") or [""])[0]
            if not album:
                album = (tags.get("album") or [""])[0]
            if not year:
                raw = (tags.get("date") or [""])[0]
                year = raw[:4] if raw else ""
            title = (tags.get("title") or [f.stem])[0]
            titles.append(title)
        except Exception:
            titles.append(f.stem)

    return ProbeResult(
        artist=artist,
        album=album,
        year=year,
        track_count=len(titles),
        track_titles=titles,
    )


def count_cue_files(cue_path: Path) -> int:
    """Count FILE entries in a CUE sheet without full parsing.

    Used by the detector to decide whether a single CUE references multiple
    audio files (multi-file CUE rip) without paying the cost of a full parse.
    Returns 0 on any read error.
    """
    try:
        content = _read_cue(cue_path)
        return sum(
            1 for line in content.splitlines()
            if re.match(r'\s*FILE\s+"', line, re.IGNORECASE)
        )
    except OSError:
        return 0


def probe_multi_file_cue(dirpath: Path) -> list[ProbeResult]:
    """Parse a multi-file CUE sheet into one ProbeResult per FILE section.

    Used when a single CUE references N audio files (e.g. a 3LP rip where
    each side is a separate FLAC all described in one master CUE).  Each
    ProbeResult covers one FILE section; timings are relative to that file's
    start (as the CUE specifies them).  track_numbers carries the original
    CUE TRACK numbers so split output is globally-numbered (e.g. 7–12 for
    Side B) rather than restarting at 1 for each side.
    """
    cue_files = sorted(dirpath.glob("*.cue")) + sorted(dirpath.glob("*.CUE"))
    if not cue_files:
        return []
    non_isrc = [f for f in cue_files if "isrc" not in f.name.lower()]
    cue_path = non_isrc[0] if non_isrc else cue_files[0]
    return _parse_multi_file_cue(cue_path, dirpath)


def _parse_multi_file_cue(cue_path: Path, dirpath: Path) -> list[ProbeResult]:
    content = _read_cue(cue_path)

    # --- first pass: global header fields (appear before any FILE block) ---
    global_performer = ""
    global_title = ""
    global_date = ""

    for line in content.splitlines():
        s = line.strip()
        if not global_performer:
            m = re.match(r'PERFORMER\s+"(.+)"', s, re.IGNORECASE)
            if m:
                global_performer = m.group(1)
        if not global_title:
            m = re.match(r'TITLE\s+"(.+)"', s, re.IGNORECASE)
            if m:
                global_title = m.group(1)
        if not global_date:
            m = re.match(r"REM\s+(?:DATE|YEAR)\s+(\d{4})", s, re.IGNORECASE)
            if m:
                global_date = m.group(1)

    if not global_title:
        global_title = dirpath.name

    if not global_date:
        for name in (dirpath.name, dirpath.parent.name):
            ym = re.match(r"^(\d{4})\b", name)
            if ym:
                global_date = ym.group(1)
                break

    # --- second pass: split into per-FILE sections ---
    # Each section: {source_file, tracks: [{number, title, start}]}
    sections: list[dict] = []
    cur_section: dict | None = None
    cur_track: dict | None = None
    pending_track: dict | None = None  # track whose INDEX 01 is in the next FILE

    for line in content.splitlines():
        s = line.strip()

        m = re.match(r'FILE\s+"(.+?)"\s*\S+', s, re.IGNORECASE)
        if m:
            # EAC "append pregap to previous track" style: TRACK N has INDEX 00
            # in FILE N-1 but its INDEX 01 is in FILE N (before any TRACK line).
            # Detect this by checking if the last track has no INDEX 01 yet.
            if cur_track is not None and cur_track["start"] is None:
                if cur_section and cur_section["tracks"] and cur_section["tracks"][-1] is cur_track:
                    cur_section["tracks"].pop()
                pending_track = cur_track
            candidate = dirpath / m.group(1)
            if not candidate.exists():
                # EAC writes .wav in the CUE even when encoding to FLAC.
                # Try every known audio extension with the same stem.
                stem = Path(m.group(1)).stem
                candidate = next(
                    (dirpath / f"{stem}{ext}" for ext in sorted(AUDIO_EXTS)
                     if (dirpath / f"{stem}{ext}").exists()),
                    candidate,
                )
            cur_section = {
                "source_file": candidate if candidate.exists() else None,
                "tracks": [],
            }
            sections.append(cur_section)
            # Carry forward the pending track from the previous FILE section.
            if pending_track is not None:
                cur_track = pending_track
                cur_section["tracks"].append(cur_track)
                pending_track = None
            else:
                cur_track = None
            continue

        if cur_section is None:
            continue

        m = re.match(r"TRACK\s+(\d+)\s+AUDIO", s, re.IGNORECASE)
        if m:
            cur_track = {"number": int(m.group(1)), "title": "", "start": None}
            cur_section["tracks"].append(cur_track)
            continue

        if cur_track is None:
            continue

        m = re.match(r'TITLE\s+"(.+)"', s, re.IGNORECASE)
        if m:
            cur_track["title"] = m.group(1)

        m = re.match(r"INDEX\s+01\s+(\d+):(\d+):(\d+)", s, re.IGNORECASE)
        if m:
            mins, secs, frames = int(m.group(1)), int(m.group(2)), int(m.group(3))
            cur_track["start"] = mins * 60 + secs + frames / 75

    # --- build one ProbeResult per section ---
    results: list[ProbeResult] = []
    for sec in sections:
        if not sec["source_file"] or not sec["tracks"]:
            continue
        tracks = sec["tracks"]
        titles = [t["title"] or f"Track {t['number']:02d}" for t in tracks]
        numbers = [t["number"] for t in tracks]
        starts = [t["start"] for t in tracks]
        timings: list[float] | None = (
            starts if (starts and all(s is not None for s in starts)) else None
        )
        results.append(ProbeResult(
            artist=global_performer,
            album=global_title,
            year=global_date,
            track_count=len(tracks),
            track_titles=titles,
            timings=timings,
            source_file=sec["source_file"],
            track_numbers=numbers,
        ))

    return results


def _parse_cue(cue_path: Path, dirpath: Path) -> ProbeResult:
    content = _read_cue(cue_path)

    global_performer = ""
    global_title = ""
    global_date = ""
    source_file: Path | None = None
    tracks: list[dict] = []
    current: dict | None = None

    for line in content.splitlines():
        line = line.strip()

        m = re.match(r'FILE\s+"(.+?)"\s+\S+', line, re.IGNORECASE)
        if m:
            candidate = dirpath / m.group(1)
            if not candidate.exists():
                # EAC writes .wav in the CUE even when encoding to FLAC.
                stem = Path(m.group(1)).stem
                candidate = next(
                    (dirpath / f"{stem}{ext}" for ext in sorted(AUDIO_EXTS)
                     if (dirpath / f"{stem}{ext}").exists()),
                    candidate,
                )
            if candidate.exists():
                source_file = candidate

        m = re.match(r"TRACK\s+\d+\s+AUDIO", line, re.IGNORECASE)
        if m:
            current = {"title": "", "performer": "", "start": None}
            tracks.append(current)
            continue

        if current is None:
            m = re.match(r'PERFORMER\s+"(.+)"', line, re.IGNORECASE)
            if m:
                global_performer = m.group(1)
            m = re.match(r'TITLE\s+"(.+)"', line, re.IGNORECASE)
            if m:
                global_title = m.group(1)
            m = re.match(r"REM\s+(?:DATE|YEAR)\s+(\d{4})", line, re.IGNORECASE)
            if m:
                global_date = m.group(1)
        else:
            m = re.match(r'TITLE\s+"(.+)"', line, re.IGNORECASE)
            if m:
                current["title"] = m.group(1)
            m = re.match(r'PERFORMER\s+"(.+)"', line, re.IGNORECASE)
            if m:
                current["performer"] = m.group(1)
            m = re.match(r"INDEX\s+01\s+(\d+):(\d+):(\d+)", line, re.IGNORECASE)
            if m:
                mins, secs, frames = int(m.group(1)), int(m.group(2)), int(m.group(3))
                current["start"] = mins * 60 + secs + frames / 75

    disc_number: int | None = None
    disc_match = re.search(
        r"\s*[(\[]?\s*(?:Disc|Disk|CD)\s*(\d+|\w+)\s*[)\]]?\s*$",
        global_title,
        re.IGNORECASE,
    )
    if disc_match:
        raw = disc_match.group(1)
        disc_number = int(raw) if raw.isdigit() else _DISC_WORDS.get(raw.lower())
        if disc_number is not None:
            global_title = global_title[: disc_match.start()].strip()

    if not global_title:
        global_title = dirpath.name

    if not global_date:
        for name in (dirpath.name, dirpath.parent.name):
            ym = re.match(r"^(\d{4})\b", name)
            if ym:
                global_date = ym.group(1)
                break

    artist = global_performer or (tracks[0]["performer"] if tracks else "")
    titles = [t["title"] or f"Track {i+1:02d}" for i, t in enumerate(tracks)]
    starts = [t["start"] for t in tracks]
    timings: list[float] | None = starts if (starts and all(s is not None for s in starts)) else None

    return ProbeResult(
        artist=artist,
        album=global_title,
        year=global_date,
        track_count=len(tracks),
        track_titles=titles,
        timings=timings,
        source_file=source_file,
        disc_number=disc_number,
    )


def _read_cue(cue_path: Path) -> str:
    for encoding in ("utf-8", "windows-1251", "latin-1"):
        try:
            return cue_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return cue_path.read_text(encoding="latin-1", errors="replace")
