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


def test_eac_pregap_companion_cuesheet_detected_as_regular(tmp_path):
    """EAC "append-pregap" companion CUE must be RegularJob, not MultiFileCueJob.

    EAC sometimes stores the pregap of TRACK N at the end of FILE N-1, giving
    FILE N-1's section two TRACK entries.  TRACK N has only INDEX 00 in FILE N-1
    and its INDEX 01 is in FILE N.  This looks like two tracks per FILE section
    but each audio file still holds exactly one complete track — it should be
    imported as a regular pre-split album.

    Reproduces the Imogen Heap - Ellipse pattern.
    """
    album = tmp_path / "album"
    album.mkdir()
    for i in range(1, 4):
        (album / f"{i:02d} - Track {i}.flac").touch()
    cue = album / "album.cue"
    # FILE 1: track 1 complete + track 2 pregap (INDEX 00 only)
    # FILE 2: track 2 INDEX 01 at start + track 3 pregap
    # FILE 3: track 3 INDEX 01 at start (implicit — no TRACK keyword)
    cue.write_text(
        'REM COMMENT "ExactAudioCopy v0.99pb5"\n'
        'FILE "01 - Track 1.wav" WAVE\n'
        "  TRACK 01 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        "    INDEX 00 03:45:00\n"
        'FILE "02 - Track 2.wav" WAVE\n'
        "    INDEX 01 00:00:00\n"
        "  TRACK 03 AUDIO\n"
        "    INDEX 00 04:12:00\n"
        'FILE "03 - Track 3.wav" WAVE\n'
        "    INDEX 01 00:00:00\n"
    )
    jobs = find_import_jobs(album)
    assert len(jobs) == 1, f"expected 1 job, got {jobs}"
    assert isinstance(jobs[0], RegularJob), f"expected RegularJob, got {type(jobs[0]).__name__}"


# ---------------------------------------------------------------------------
# Single-file rips: finding the CUE sheet without ever guessing
# ---------------------------------------------------------------------------

def test_cue_in_audio_free_subfolder(tmp_path):
    """Night Sun / King Crimson layout: the sheet sits in log+cue/ beside nothing but logs."""
    album = tmp_path / "Night Sun - Mournin'"
    _touch(album, "Mournin'.wv")
    sheet = _touch(album, "log+cue/Mournin'.cue")
    _touch(album, "log+cue/Mournin'.log")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)
    assert jobs[0].path == album
    assert jobs[0].cue == sheet


def test_two_albums_in_one_download_stay_two_jobs(tmp_path):
    """Tim Maia Racional: Vol. 1/ and Vol. 2/ each hold their own .flac + .cue."""
    root = tmp_path / "Tim Maia - Racional"
    for vol in ("Vol. 1", "Vol. 2"):
        _touch(root, f"{vol}/Racional {vol}.flac")
        _touch(root, f"{vol}/Racional {vol}.cue")
    jobs = find_import_jobs(root)
    assert sorted(j.path.name for j in jobs) == ["Vol. 1", "Vol. 2"]
    assert all(isinstance(j, CueRipJob) for j in jobs)
    assert all(j.cue.parent == j.path for j in jobs)


def _sheet(path: Path, file_name: str, second_index: str, title: str = "Two") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'FILE "{file_name}" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "One"\n    INDEX 01 00:00:00\n'
        f'  TRACK 02 AUDIO\n    TITLE "{title}"\n    INDEX 01 {second_index}\n'
    )
    return path


def test_one_audio_two_sheets_is_ambiguous(tmp_path):
    from app.pipeline.detector import AmbiguousCueJob

    album = tmp_path / "album"
    _touch(album, "album.flac")
    a = _sheet(album / "album.cue", "album.flac", "03:00:00")
    b = _sheet(album / "album (alt).cue", "album.flac", "03:12:40")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], AmbiguousCueJob)
    assert sorted(jobs[0].sheets) == sorted([a, b])


def test_sheets_across_subfolders_are_ambiguous(tmp_path):
    from app.pipeline.detector import AmbiguousCueJob

    album = tmp_path / "album"
    _touch(album, "album.wv")
    _sheet(album / "cue" / "album.cue", "album.wv", "03:00:00")
    _sheet(album / "eac" / "album.cue", "album.wv", "04:00:00")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], AmbiguousCueJob)
    assert len(jobs[0].sheets) == 2


def test_sheets_with_the_same_split_count_as_one(tmp_path):
    """X.cue + X.flac.cue: same timings, same audio, only FILE line and titles differ."""
    album = tmp_path / "Death - Symbolic"
    _touch(album, "Symbolic.flac")
    _sheet(album / "Symbolic.wav.cue", "Symbolic.wav", "03:00:00", title="Zero Tolerance")
    _sheet(album / "Symbolic.flac.cue", "Symbolic.flac", "03:00:00", title="ZERO TOLERANCE")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)


def test_same_timings_naming_different_audio_stay_ambiguous(tmp_path):
    from app.pipeline.detector import AmbiguousCueJob

    album = tmp_path / "album"
    _touch(album, "album.flac")
    _sheet(album / "album.cue", "album.flac", "03:00:00")
    _sheet(album / "bonus.cue", "bonus disc.flac", "03:00:00")
    jobs = find_import_jobs(album)
    assert isinstance(jobs[0], AmbiguousCueJob)


def test_subfolder_search_skipped_when_a_subfolder_has_audio(tmp_path):
    """A sheet beside other audio belongs to that audio, never to the parent's file."""
    album = tmp_path / "album"
    _touch(album, "hidden track.flac")
    _touch(album, "extra/extra.flac")
    _touch(album, "extra/extra.cue")
    jobs = find_import_jobs(album)
    assert len(jobs) == 1
    assert isinstance(jobs[0], CueRipJob)
    assert jobs[0].path == album / "extra"
