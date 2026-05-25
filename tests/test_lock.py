import json
import os
import time


def test_acquire_and_is_locked(tmp_path):
    import app.config as cfg

    cfg.LOCK_FILE = str(tmp_path / "manual-match.lock")

    from app.lock import acquire_lock, is_locked, release_lock

    assert not is_locked()
    assert acquire_lock("/some/stage/path") is True
    assert is_locked()
    assert acquire_lock("/another/path") is False  # already locked — atomic reject
    release_lock()
    assert not is_locked()


def test_cleanup_stale_lock(tmp_path):
    import app.config as cfg

    cfg.LOCK_FILE = str(tmp_path / "manual-match.lock")

    lock_file = tmp_path / "manual-match.lock"
    lock_file.write_text(json.dumps({"path": "/x", "ts": time.time() - 7200}))

    from app.lock import cleanup_stale_lock, is_locked

    cleanup_stale_lock()
    assert not is_locked()


def test_fresh_lock_not_cleaned(tmp_path):
    import app.config as cfg

    cfg.LOCK_FILE = str(tmp_path / "manual-match.lock")

    from app.lock import acquire_lock, cleanup_stale_lock, is_locked

    acquire_lock("/some/path")
    cleanup_stale_lock()
    assert is_locked()  # fresh lock should remain
