import json
import os
import time
from typing import Any

from app import config

LOCK_MAX_AGE_SECONDS = 120  # 2 minutes — auto-expire if generator finally block didn't run


def acquire_lock(stage_path: str) -> bool:
    """Atomically acquire the lock. Returns True if acquired, False if already locked."""
    cleanup_stale_lock()
    try:
        with open(config.LOCK_FILE, "x") as f:
            json.dump({"path": stage_path, "ts": time.time()}, f)
        return True
    except FileExistsError:
        return False


def release_lock() -> None:
    try:
        os.remove(config.LOCK_FILE)
    except FileNotFoundError:
        pass


def is_locked() -> bool:
    return os.path.exists(config.LOCK_FILE)


def get_lock_info() -> dict[str, Any] | None:
    try:
        with open(config.LOCK_FILE) as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def cleanup_stale_lock() -> None:
    info = get_lock_info()
    if info is None:
        return
    age = time.time() - info.get("ts", 0)
    if age > LOCK_MAX_AGE_SECONDS:
        release_lock()
