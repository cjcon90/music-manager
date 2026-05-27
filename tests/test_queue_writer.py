import re
from pathlib import Path

import pytest

import app.config as cfg
from app.queue_writer import write_queue_job


@pytest.fixture(autouse=True)
def patch_queue_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "IMPORT_QUEUE_DIR", str(tmp_path / "queue"))


def test_creates_path_file_with_correct_content(tmp_path):
    result = write_queue_job("/data/downloads/complete/music/Album")
    assert result.exists()
    lines = result.read_text().splitlines()
    assert lines[0] == "/data/downloads/complete/music/Album"
    assert "--noincremental" in lines


def test_noincremental_false_omits_flag(tmp_path):
    result = write_queue_job("/some/path", noincremental=False)
    lines = result.read_text().splitlines()
    assert "--noincremental" not in lines


def test_search_id_written_when_provided(tmp_path):
    uuid = "12345678-1234-1234-1234-123456789012"
    result = write_queue_job("/some/path", search_id=uuid)
    lines = result.read_text().splitlines()
    assert f"--search-id={uuid}" in lines


def test_search_id_omitted_when_none(tmp_path):
    result = write_queue_job("/some/path", search_id=None)
    content = result.read_text()
    assert "--search-id" not in content


def test_move_flag_written_when_true(tmp_path):
    result = write_queue_job("/some/path", move=True)
    lines = result.read_text().splitlines()
    assert "--move" in lines


def test_move_flag_omitted_when_false(tmp_path):
    result = write_queue_job("/some/path", move=False)
    content = result.read_text()
    assert "--move" not in content


def test_prefix_appears_in_filename(tmp_path):
    result = write_queue_job("/some/path", prefix="rematch")
    assert result.name.startswith("rematch-")


def test_queue_dir_created_if_missing(tmp_path):
    # autouse fixture sets IMPORT_QUEUE_DIR to a non-existent subdir
    result = write_queue_job("/some/path")
    assert result.parent.is_dir()


def test_returns_path_object(tmp_path):
    result = write_queue_job("/some/path")
    assert isinstance(result, Path)


def test_two_calls_produce_unique_filenames(tmp_path):
    a = write_queue_job("/path/a")
    b = write_queue_job("/path/b")
    assert a != b
