import os
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline import AUDIO_EXTS, DISC_PATTERN

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
class RegularJob:
    path: Path
    kind: str = field(default="regular", init=False)


@dataclass
class MultiDiscJob:
    path: Path
    kind: str = field(default="multi_disc", init=False)


ImportJob = CueRipJob | MultiCueRipJob | RegularJob | MultiDiscJob


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


def _is_regular(filenames: list[str]) -> bool:
    return len(_audio_files(filenames)) >= 2


def _is_multi_disc(dirnames: list[str]) -> bool:
    return any(DISC_PATTERN.match(d) for d in dirnames)
