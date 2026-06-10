import re
from pathlib import Path

import pytest

import app.config as cfg
from app.queue_writer import write_queue_job


@pytest.fixture(autouse=True)
def patch_queue_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "IMPORT_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setattr(cfg, "IMPORT_BASE_DIR", "/data/downloads/complete/music")
    monkeypatch.setattr(cfg, "IMPORT_STAGE_DIR", "/data/import-stage")
    monkeypatch.setattr(cfg, "MUSIC_LIBRARY_DIR", "/data/music")


def test_creates_path_file_with_correct_content(tmp_path):
    result = write_queue_job("/data/downloads/complete/music/Album")
    assert result.exists()
    lines = result.read_text().splitlines()
    assert lines[0] == "/data/downloads/complete/music/Album"
    assert "--noincremental" in lines


def test_noincremental_false_omits_flag(tmp_path):
    result = write_queue_job("/data/music/path", noincremental=False)
    lines = result.read_text().splitlines()
    assert "--noincremental" not in lines


def test_search_id_written_when_provided(tmp_path):
    uuid = "12345678-1234-1234-1234-123456789012"
    result = write_queue_job("/data/music/path", search_id=uuid)
    lines = result.read_text().splitlines()
    assert f"--search-id={uuid}" in lines


def test_search_id_omitted_when_none(tmp_path):
    result = write_queue_job("/data/music/path", search_id=None)
    content = result.read_text()
    assert "--search-id" not in content


def test_move_flag_written_when_true(tmp_path):
    result = write_queue_job("/data/music/path", move=True)
    lines = result.read_text().splitlines()
    assert "--move" in lines


def test_move_flag_omitted_when_false(tmp_path):
    result = write_queue_job("/data/music/path", move=False)
    content = result.read_text()
    assert "--move" not in content


def test_prefix_appears_in_filename(tmp_path):
    result = write_queue_job("/data/music/path", prefix="rematch")
    assert result.name.startswith("rematch-")


def test_queue_dir_created_if_missing(tmp_path):
    # autouse fixture sets IMPORT_QUEUE_DIR to a non-existent subdir
    result = write_queue_job("/data/music/path")
    assert result.parent.is_dir()


def test_returns_path_object(tmp_path):
    result = write_queue_job("/data/music/path")
    assert isinstance(result, Path)


def test_two_calls_produce_unique_filenames(tmp_path):
    a = write_queue_job("/data/music/a")
    b = write_queue_job("/data/music/b")
    assert a != b


def test_raises_on_newline_in_path(tmp_path):
    with pytest.raises(ValueError, match="newlines"):
        write_queue_job("/data/music/album\n--injected")


def test_raises_on_invalid_search_id(tmp_path):
    with pytest.raises(ValueError, match="UUID"):
        write_queue_job("/data/music/album", search_id="not-a-uuid")


def test_accepts_valid_search_id(tmp_path):
    # compact UUID format
    pf = write_queue_job("/data/music/album", search_id="a1b2c3d4e5f647a8b9c0d1e2f3a4b5c6")
    assert "--search-id=a1b2c3d4e5f647a8b9c0d1e2f3a4b5c6" in pf.read_text()
    # hyphenated UUID format
    pf2 = write_queue_job("/data/music/album2", search_id="a1b2c3d4-e5f6-47a8-b9c0-d1e2f3a4b5c6")
    assert "--search-id=a1b2c3d4-e5f6-47a8-b9c0-d1e2f3a4b5c6" in pf2.read_text()


def test_raises_on_path_outside_allowed_roots(tmp_path):
    """Routes pass user-supplied paths straight here — the queue writer is the
    central chokepoint, so it must reject paths outside the import roots."""
    with pytest.raises(ValueError, match="allowed roots"):
        write_queue_job("/etc/passwd")


def test_raises_on_parent_traversal_to_outside_root(tmp_path):
    with pytest.raises(ValueError, match="allowed roots"):
        write_queue_job("/data/music/../../etc")


def test_accepts_paths_under_each_allowed_root(tmp_path):
    for p in (
        "/data/downloads/complete/music/Album",
        "/data/import-stage/abc123",
        "/data/music/Artist/Album",
    ):
        assert write_queue_job(p).exists()
