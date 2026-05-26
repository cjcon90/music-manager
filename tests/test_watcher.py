import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.config as config
from app.watcher import _read_path_file, _watcher_loop, start_watcher


@pytest.fixture(autouse=True)
def patch_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IMPORT_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setattr(config, "IMPORT_ACTIVE_FILE", str(tmp_path / "import-active"))
    (tmp_path / "queue").mkdir()


def test_read_path_file_returns_path_and_flags(tmp_path):
    f = tmp_path / "test.path"
    f.write_text("/media/downloads/album\n--noincremental\n")
    path, flags = _read_path_file(f)
    assert path == "/media/downloads/album"
    assert "--noincremental" in flags


def test_read_path_file_no_flags(tmp_path):
    f = tmp_path / "test.path"
    f.write_text("/media/downloads/album\n")
    path, flags = _read_path_file(f)
    assert path == "/media/downloads/album"
    assert flags == []


def test_watcher_loop_processes_path_file(tmp_path):
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    path_file = queue_dir / "001.path"
    path_file.write_text("/media/downloads/album\n")

    with patch("app.watcher.runner") as mock_runner:
        # Run exactly one iteration via a side-effect that stops the loop
        call_count = 0

        def fake_run(path, noincremental=True, mb_id_override=None, move=False):
            nonlocal call_count
            call_count += 1

        mock_runner.run.side_effect = fake_run

        # Patch time.sleep to raise after first call so loop exits
        with patch("app.watcher.time.sleep", side_effect=StopIteration):
            try:
                _watcher_loop()
            except StopIteration:
                pass

        assert call_count == 1
        mock_runner.run.assert_called_once_with("/media/downloads/album", noincremental=False, mb_id_override=None, move=False)
        assert not path_file.exists()


def test_watcher_loop_passes_noincremental_flag(tmp_path):
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    path_file = queue_dir / "001.path"
    path_file.write_text("/media/downloads/album\n--noincremental\n")

    with patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        try:
            _watcher_loop()
        except StopIteration:
            pass

        mock_runner.run.assert_called_once_with("/media/downloads/album", noincremental=True, mb_id_override=None, move=False)


def test_watcher_loop_writes_active_file(tmp_path):
    active_file = Path(config.IMPORT_ACTIVE_FILE)
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    (queue_dir / "001.path").write_text("/media/downloads/album\n")

    seen_active = []

    def fake_run(path, noincremental=True, mb_id_override=None, move=False):
        seen_active.append(active_file.read_text().strip() if active_file.exists() else None)

    with patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        mock_runner.run.side_effect = fake_run
        try:
            _watcher_loop()
        except StopIteration:
            pass

    assert seen_active == ["/media/downloads/album"]
    assert not active_file.exists()


def test_watcher_loop_continues_after_runner_crash(tmp_path):
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    (queue_dir / "001.path").write_text("/media/downloads/album1\n")
    (queue_dir / "002.path").write_text("/media/downloads/album2\n")

    calls = []

    def fake_run(path, noincremental=True, mb_id_override=None, move=False):
        calls.append(path)
        if "album1" in path:
            raise RuntimeError("runner crashed")

    with patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        mock_runner.run.side_effect = fake_run
        try:
            _watcher_loop()
        except StopIteration:
            pass

    assert len(calls) == 2


def test_start_watcher_disabled_by_env(monkeypatch):
    monkeypatch.setenv("WATCHER_DISABLE", "1")
    before = threading.active_count()
    start_watcher()
    assert threading.active_count() == before


def test_start_watcher_creates_daemon_thread(monkeypatch):
    monkeypatch.delenv("WATCHER_DISABLE", raising=False)
    before = threading.active_count()
    with patch("app.watcher._watcher_loop", side_effect=lambda: time.sleep(0.5)):
        start_watcher()
        assert threading.active_count() > before
