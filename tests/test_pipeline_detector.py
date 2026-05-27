import os
from pathlib import Path

import pytest

from app.pipeline.detector import CueRipJob, MultiDiscJob, RegularJob, find_import_jobs


def _touch(path: Path, name: str) -> Path:
    p = path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


def test_flat_cue_rip(tmp_path):
    _touch(tmp_path, "album/album.flac")
    _touch(tmp_path, "album/album.cue")
    jobs = find_import_jobs(tmp_path / "album")
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)


def test_flat_regular(tmp_path):
    for i in range(3):
        _touch(tmp_path, f"album/{i:02d}.flac")
    jobs = find_import_jobs(tmp_path / "album")
    assert len(jobs) == 1
    assert isinstance(jobs[0], RegularJob)


def test_multi_disc_cue(tmp_path):
    album = tmp_path / "album"
    _touch(album, "CD1/disc1.flac")
    _touch(album, "CD1/disc1.cue")
    _touch(album, "CD2/disc2.flac")
    _touch(album, "CD2/disc2.cue")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], MultiDiscJob)
    assert jobs[0].path == album


def test_multi_disc_regular(tmp_path):
    album = tmp_path / "album"
    for i in range(3):
        _touch(album, f"Disc 1/{i:02d}.flac")
        _touch(album, f"Disc 2/{i:02d}.flac")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], MultiDiscJob)


def test_deep_cue(tmp_path):
    # artist/era/album/edition/file.flac + .cue  (depth 4 relative to root)
    deep = tmp_path / "artist" / "era" / "album" / "edition"
    _touch(deep, "album.flac")
    _touch(deep, "album.cue")
    jobs = find_import_jobs(tmp_path)
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)
    assert jobs[0].path == deep


def test_discography(tmp_path):
    for name in ["1996-album1", "1999-album2"]:
        for i in range(3):
            _touch(tmp_path, f"{name}/{i:02d}.flac")
    jobs = find_import_jobs(tmp_path)
    assert len(jobs) == 2
    assert all(isinstance(j, RegularJob) for j in jobs)


def test_empty_dir(tmp_path):
    (tmp_path / "album").mkdir()
    jobs = find_import_jobs(tmp_path / "album")
    assert jobs == []


def test_max_depth_guard(tmp_path):
    # Build 11 levels deep with a CUE at the bottom
    deep = tmp_path
    for i in range(11):
        deep = deep / f"l{i}"
    _touch(deep, "album.flac")
    _touch(deep, "album.cue")
    jobs = find_import_jobs(tmp_path)
    assert jobs == []


def test_no_symlink_loop(tmp_path):
    album = tmp_path / "album"
    album.mkdir()
    _touch(album, "track.flac")
    _touch(album, "album.cue")
    loop = album / "loop"
    loop.symlink_to(tmp_path)  # symlink to ancestor
    jobs = find_import_jobs(tmp_path)
    # Must return without hanging; symlink not followed
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)


def test_regular_job_detected_for_dsf_files(tmp_path):
    """DSD albums (.dsf) must be classified as RegularJob, not skipped."""
    (tmp_path / 'track01.dsf').touch()
    (tmp_path / 'track02.dsf').touch()
    jobs = find_import_jobs(tmp_path)
    assert len(jobs) == 1
    assert isinstance(jobs[0], RegularJob)


def test_regular_job_detected_for_dff_files(tmp_path):
    """DSD albums (.dff) must be classified as RegularJob, not skipped."""
    (tmp_path / 'track01.dff').touch()
    (tmp_path / 'track02.dff').touch()
    jobs = find_import_jobs(tmp_path)
    assert len(jobs) == 1
    assert isinstance(jobs[0], RegularJob)

def test_companion_cuesheet_detected_as_regular(tmp_path):
    """Pre-split album with EAC companion cuesheet (1 track per FILE) must be RegularJob.

    Reproduces the Captain Beyond / Basement Jaxx bug: count_cue_files == len(audio)
    by coincidence, but these are already-split FLACs — not a multi-file rip needing splitting.
    """
    album = tmp_path / "album"
    album.mkdir()
    for i in range(1, 4):
        (album / f"{i:02d} - Track {i}.flac").touch()
    cue = album / "album.cue"
    cue.write_text(
        'REM COMMENT "EAC"\n'
        'FILE "01 - Track 1.wav" WAVE\n'
        "  TRACK 01 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        'FILE "02 - Track 2.wav" WAVE\n'
        "  TRACK 02 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        'FILE "03 - Track 3.wav" WAVE\n'
        "  TRACK 03 AUDIO\n"
        "    INDEX 01 00:00:00\n"
    )
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], RegularJob)


def test_true_multi_file_cue_detected(tmp_path):
    """True multi-file CUE rip (each FILE has multiple tracks) must be MultiFileCueJob."""
    from app.pipeline.detector import MultiFileCueJob

    album = tmp_path / "album"
    album.mkdir()
    (album / "side_a.flac").touch()
    (album / "side_b.flac").touch()
    cue = album / "album.cue"
    cue.write_text(
        'FILE "side_a.flac" WAVE\n'
        "  TRACK 01 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        "    INDEX 01 03:00:00\n"
        "  TRACK 03 AUDIO\n"
        "    INDEX 01 06:00:00\n"
        'FILE "side_b.flac" WAVE\n'
        "  TRACK 04 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        "  TRACK 05 AUDIO\n"
        "    INDEX 01 04:00:00\n"
    )
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], MultiFileCueJob)
