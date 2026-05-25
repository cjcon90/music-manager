import shutil
from pathlib import Path

import pytest
from mutagen.flac import FLAC

from app.pipeline.probe import ProbeResult, probe_cue, probe_flac

FIXTURES = Path(__file__).parent / "fixtures" / "cue"


def _cue_dir(tmp_path: Path, fixture_name: str) -> Path:
    """Copy a CUE fixture into a temp dir (no audio file — source_file will be None)."""
    d = tmp_path / "album"
    d.mkdir()
    shutil.copy(FIXTURES / fixture_name, d / fixture_name)
    return d


def test_probe_cue_utf8(tmp_path):
    d = _cue_dir(tmp_path, "utf8_single_disc.cue")
    r = probe_cue(d)
    assert r.artist == "Billie Holiday"
    assert r.album == "Lady in Satin"
    assert r.year == "1958"
    assert r.track_count == 3
    assert r.track_titles[0] == "I'm a Fool to Want You"
    assert len(r.timings) == 3
    assert r.timings[0] == 0.0
    assert r.disc_number is None


def test_probe_cue_multi_disc_strips_suffix(tmp_path):
    d = _cue_dir(tmp_path, "multi_disc_cd1.cue")
    r = probe_cue(d)
    assert r.album == "The Complete Albums Collection"
    assert r.disc_number == 1


def test_probe_cue_per_track_performer(tmp_path):
    d = _cue_dir(tmp_path, "per_track_performer.cue")
    r = probe_cue(d)
    assert r.artist == "Billie Holiday"
    assert r.album == "At Newport"
    assert r.track_count == 2


def test_probe_cue_no_date_falls_back_to_folder(tmp_path):
    d = _cue_dir(tmp_path, "no_date.cue")
    r = probe_cue(d)
    assert r.year == ""  # folder name "album" has no year prefix

    # Rename dir to have year prefix and re-test
    d2 = tmp_path / "1959 - Strange Fruit"
    d.rename(d2)
    r2 = probe_cue(d2)
    assert r2.year == "1959"


def test_probe_cue_ape_source_name(tmp_path):
    d = _cue_dir(tmp_path, "ape_source.cue")
    r = probe_cue(d)
    assert r.source_file is None  # .ape doesn't exist in tmp dir
    assert r.track_titles[0] == "God Bless the Child"


def test_probe_cue_latin1(tmp_path):
    d = _cue_dir(tmp_path, "latin1.cue")
    r = probe_cue(d)
    assert "Billie Holiday" in r.artist
    assert r.year == "1941"


def test_probe_cue_windows1251(tmp_path, windows1251_cue):
    d = tmp_path / "album"
    d.mkdir()
    shutil.copy(windows1251_cue, d / "album.cue")
    r = probe_cue(d)
    assert r.year == "1961"
    assert r.track_count == 1


def test_probe_cue_source_file_found(tmp_path, silence_flac):
    d = tmp_path / "album"
    d.mkdir()
    shutil.copy(FIXTURES / "utf8_single_disc.cue", d / "utf8_single_disc.cue")
    audio = d / "Lady in Satin.flac"
    shutil.copy(silence_flac, audio)
    r = probe_cue(d)
    assert r.source_file == audio


def test_probe_cue_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    r = probe_cue(d)
    assert r == ProbeResult()


def test_probe_flac_full_tags(tmp_path, silence_flac):
    d = tmp_path / "album"
    d.mkdir()
    for i in range(3):
        dest = d / f"{i+1:02d} - Track {i+1}.flac"
        shutil.copy(silence_flac, dest)
        tags = FLAC(str(dest))
        tags["albumartist"] = ["Test Artist"]
        tags["album"] = ["Test Album"]
        tags["date"] = ["2020"]
        tags["title"] = [f"Track {i+1}"]
        tags.save()
    r = probe_flac(d)
    assert r.artist == "Test Artist"
    assert r.album == "Test Album"
    assert r.year == "2020"
    assert r.track_count == 3
    assert r.track_titles == ["Track 1", "Track 2", "Track 3"]


def test_probe_flac_artist_fallback(tmp_path, silence_flac):
    dest = tmp_path / "01.flac"
    shutil.copy(silence_flac, dest)
    tags = FLAC(str(dest))
    tags["artist"] = ["Solo Artist"]
    tags["album"] = ["My Album"]
    tags.save()
    r = probe_flac(tmp_path)
    assert r.artist == "Solo Artist"


def test_probe_flac_missing_year(tmp_path, silence_flac):
    for i in range(2):
        dest = tmp_path / f"{i+1:02d}.flac"
        shutil.copy(silence_flac, dest)
        tags = FLAC(str(dest))
        tags["albumartist"] = ["Artist"]
        tags.save()
    r = probe_flac(tmp_path)
    assert r.year == ""


def test_probe_flac_empty_dir(tmp_path):
    r = probe_flac(tmp_path)
    assert r == ProbeResult()
