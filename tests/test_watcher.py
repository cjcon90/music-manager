import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.config as config
from app.watcher import (
    _read_path_file,
    _recover_interrupted_import,
    _watcher_loop,
    start_watcher,
)


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
        raw = active_file.read_text() if active_file.exists() else None
        seen_active.append(json.loads(raw)["path"] if raw else None)

    with patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        mock_runner.run.side_effect = fake_run
        try:
            _watcher_loop()
        except StopIteration:
            pass

    assert seen_active == ["/media/downloads/album"]
    assert not active_file.exists()


def test_watcher_loop_writes_flags_to_active_file(tmp_path):
    """The active file must record all flags so recovery can resume a rematch
    faithfully (path alone would silently drop --search-id and --move)."""
    active_file = Path(config.IMPORT_ACTIVE_FILE)
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    uuid = "12345678-1234-1234-1234-123456789012"
    (queue_dir / "001.path").write_text(
        f"/media/downloads/album\n--noincremental\n--search-id={uuid}\n--move\n"
    )

    seen = []

    def fake_run(path, noincremental=True, mb_id_override=None, move=False):
        seen.append(json.loads(active_file.read_text()))

    with patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        mock_runner.run.side_effect = fake_run
        try:
            _watcher_loop()
        except StopIteration:
            pass

    assert seen == [{
        "path": "/media/downloads/album",
        "noincremental": True,
        "search_id": uuid,
        "move": True,
    }]


def test_watcher_loop_survives_queue_file_removed_mid_iteration(tmp_path):
    """Race: /queue/remove deletes a .path file between the watcher's glob and
    its unlink — the watcher thread must not die, and the rest of the queue
    must still be processed."""
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    (queue_dir / "001.path").write_text("/media/downloads/album1\n")
    (queue_dir / "002.path").write_text("/media/downloads/album2\n")

    real_read = _read_path_file

    def racy_read(path_file):
        result = real_read(path_file)
        if path_file.name == "001.path":
            path_file.unlink()  # the queue UI removed it first
        return result

    with patch("app.watcher._read_path_file", side_effect=racy_read), \
         patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        try:
            _watcher_loop()
        except StopIteration:
            pass

    processed = [c.args[0] for c in mock_runner.run.call_args_list]
    assert "/media/downloads/album2" in processed


def test_watcher_loop_survives_read_error_and_drops_poison_file(tmp_path):
    """An unreadable .path file must be dropped — not kill the watcher thread,
    and not be retried forever."""
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    (queue_dir / "001.path").write_text("/media/downloads/album1\n")
    (queue_dir / "002.path").write_text("/media/downloads/album2\n")

    real_read = _read_path_file

    def broken_read(path_file):
        if path_file.name == "001.path":
            raise OSError("unreadable")
        return real_read(path_file)

    with patch("app.watcher._read_path_file", side_effect=broken_read), \
         patch("app.watcher.runner") as mock_runner, \
         patch("app.watcher.time.sleep", side_effect=StopIteration):
        try:
            _watcher_loop()
        except StopIteration:
            pass

    processed = [c.args[0] for c in mock_runner.run.call_args_list]
    assert processed == ["/media/downloads/album2"]
    assert not (queue_dir / "001.path").exists()


def test_recover_interrupted_import_preserves_flags(tmp_path):
    uuid = "12345678-1234-1234-1234-123456789012"
    active_file = Path(config.IMPORT_ACTIVE_FILE)
    active_file.write_text(json.dumps({
        "path": "/media/downloads/album",
        "noincremental": True,
        "search_id": uuid,
        "move": True,
    }))

    with patch("app.watcher.write_queue_job") as mock_write:
        _recover_interrupted_import()

    mock_write.assert_called_once_with(
        "/media/downloads/album",
        noincremental=True,
        search_id=uuid,
        move=True,
        prefix="recovery",
    )
    assert not active_file.exists()


def test_recover_interrupted_import_handles_legacy_plain_text(tmp_path):
    active_file = Path(config.IMPORT_ACTIVE_FILE)
    active_file.write_text("/media/downloads/album\n")

    with patch("app.watcher.write_queue_job") as mock_write:
        _recover_interrupted_import()

    assert mock_write.call_args.args == ("/media/downloads/album",)
    assert not active_file.exists()


def test_get_active_parses_json_active_file(tmp_path):
    from app.routes.queue import get_active

    Path(config.IMPORT_ACTIVE_FILE).write_text(json.dumps({
        "path": "/media/downloads/album",
        "noincremental": True,
        "search_id": None,
        "move": False,
    }))

    active = get_active()
    assert active is not None
    assert active["path"] == "/media/downloads/album"


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
