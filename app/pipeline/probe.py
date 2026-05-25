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
