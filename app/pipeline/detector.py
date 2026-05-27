import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline import AUDIO_EXTS, DISC_PATTERN
from app.pipeline.probe import count_cue_files

MAX_WALK_DEPTH = 10


@dataclass
class CueRipJob:
    path: Path
    kind: str = field(default="cue_rip", init=False)


@dataclass
class MultiCueRipJob:
    path: Path
    kind: str = field(default="multi_cue_rip", init=False)


@dataclass
class MultiFileCueJob:
    path: Path
    kind: str = field(default="multi_file_cue", init=False)


@dataclass
class RegularJob:
    path: Path
    kind: str = field(default="regular", init=False)


@dataclass
class MultiDiscJob:
    path: Path
    kind: str = field(default="multi_disc", init=False)


ImportJob = CueRipJob | MultiCueRipJob | MultiFileCueJob | RegularJob | MultiDiscJob


def find_import_jobs(root: Path) -> list[ImportJob]:
    jobs: list[ImportJob] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= MAX_WALK_DEPTH:
            dirnames.clear()
            continue
        dp = Path(dirpath)
        if _is_cue_rip(filenames):
            jobs.append(CueRipJob(dp))
            dirnames.clear()
        elif _is_multi_cue_rip(filenames):
            jobs.append(MultiCueRipJob(dp))
            dirnames.clear()
        elif _is_multi_file_cue(filenames, dp):
            jobs.append(MultiFileCueJob(dp))
            dirnames.clear()
        elif _is_regular(filenames):
            jobs.append(RegularJob(dp))
            dirnames.clear()
        elif _is_multi_disc(dirnames):
            jobs.append(MultiDiscJob(dp))
            dirnames.clear()
    return jobs


def _audio_files(filenames: list[str]) -> list[str]:
    return [f for f in filenames if Path(f).suffix.lower() in AUDIO_EXTS]


def _is_cue_rip(filenames: list[str]) -> bool:
    audio = _audio_files(filenames)
    cue = [f for f in filenames if f.lower().endswith(".cue")]
    return len(audio) == 1 and len(cue) >= 1


def _is_multi_cue_rip(filenames: list[str]) -> bool:
    """Multiple FLAC+CUE pairs in one directory — e.g. a 2-disc album as two whole-disc rips."""
    audio = _audio_files(filenames)
    cue = [f for f in filenames if f.lower().endswith(".cue") and "isrc" not in f.lower()]
    return len(audio) >= 2 and len(cue) == len(audio)


def _is_multi_file_cue(filenames: list[str], dirpath: Path) -> bool:
    """Single CUE referencing N audio files — e.g. a 3LP rip with one master CUE for all sides.

    Distinct from MultiCueRipJob (N CUEs, one per audio file): here a single CUE sheet
    contains N FILE entries, each pointing to one of the audio files in the directory.
    We peek inside the CUE to count FILE entries rather than inferring from filename counts.
    """
    audio = _audio_files(filenames)
    cue = [f for f in filenames if f.lower().endswith(".cue") and "isrc" not in f.lower()]
    if len(audio) < 2 or len(cue) != 1:
        return False
    return count_cue_files(dirpath / cue[0]) == len(audio)


def _is_regular(filenames: list[str]) -> bool:
    return len(_audio_files(filenames)) >= 2


def _is_multi_disc(dirnames: list[str]) -> bool:
    return any(DISC_PATTERN.match(d) for d in dirnames)


# Relaxed pattern for pre-detection overrides: matches "CD01 - Title", "Disc 2 - ...", etc.
# The strict DISC_PATTERN (used by _is_multi_disc) requires a plain "CD1" form.
RELAXED_DISC_PATTERN: re.Pattern[str] = re.compile(r"^(?:cd|disc|disk)\s*\d+\b", re.IGNORECASE)


def disc_is_image_cue(d: Path) -> bool:
    """Return True if this directory contains an unsplit disc image: one audio file + CUE.

    Pre-split albums sometimes include a leftover .cue alongside individual tracks;
    those are NOT disc images and must not trigger CUE splitting.
    """
    audio = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
    cue = list(d.glob("*.cue")) + list(d.glob("*.CUE"))
    return len(audio) == 1 and len(cue) >= 1


def looks_like_multi_disc_cue_rip(root: Path) -> bool:
    """Return True if root contains ≥2 subdirs that each look like disc-image CUE rips.

    Uses RELAXED_DISC_PATTERN so "CD01 - Title" matches even though the strict
    DISC_PATTERN requires a clean "CD1" form. Only relevant when mb_id_override
    is set — never called during fully automatic imports.
    """
    try:
        disc_dirs = [
            d for d in root.iterdir()
            if d.is_dir() and RELAXED_DISC_PATTERN.match(d.name)
        ]
    except OSError:
        return False
    return len(disc_dirs) >= 2 and all(disc_is_image_cue(d) for d in disc_dirs)


def looks_like_multi_disc_regular(root: Path) -> bool:
    """Return True if root has ≥2 subdirs each containing audio but no audio in root itself.

    Detects multi-disc releases with descriptive subdir names (e.g. disc titles) that
    don't match DISC_PATTERN. Gated on mb_id_override in runner — never fires during
    automatic imports.
    """
    try:
        if any(f.is_file() and f.suffix.lower() in AUDIO_EXTS for f in root.iterdir()):
            return False
        audio_subdirs = [
            d for d in root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and any(f.is_file() and f.suffix.lower() in AUDIO_EXTS for f in d.iterdir())
        ]
        return len(audio_subdirs) >= 2
    except OSError:
        return False
