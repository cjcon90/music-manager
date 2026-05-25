import hashlib
import logging
import os
import threading
import time
from pathlib import Path

from app import config
from app.pipeline import runner

log = logging.getLogger(__name__)


def start_watcher() -> None:
    if os.environ.get("WATCHER_DISABLE"):
        return
    _recover_interrupted_import()
    t = threading.Thread(target=_watcher_loop, name="import-watcher", daemon=True)
    t.start()
    log.info("Import watcher started")


def _recover_interrupted_import() -> None:
    """Re-queue any import that was interrupted by a container restart.

    The watcher writes the current path to IMPORT_ACTIVE_FILE before calling
    runner.run() and removes it in the finally block. If the container is killed
    mid-import, that file remains. On the next startup we re-queue the path so
    the import is retried automatically rather than silently abandoned.
    """
    active = Path(config.IMPORT_ACTIVE_FILE)
    if not active.exists():
        return
    path = active.read_text().strip()
    active.unlink(missing_ok=True)
    if not path:
        return
    log.warning("Detected interrupted import for %s — re-queuing", path)
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
    tag = hashlib.sha256(f"{path}{time.time()}".encode()).hexdigest()[:8]
    recovery_file = queue_dir / f"recovery-{tag}.path"
    recovery_file.write_text(f"{path}\n--noincremental\n")


def _watcher_loop() -> None:
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
    # Ensure world-writable so qBittorrent's on-complete.sh (different container user) can write path files
    queue_dir.chmod(0o777)

    while True:
        for path_file in sorted(queue_dir.glob("*.path")):
            path, flags = _read_path_file(path_file)
            if not path:
                path_file.unlink(missing_ok=True)
                continue
            path_file.unlink()
            Path(config.IMPORT_ACTIVE_FILE).write_text(path)
            noincremental = "--noincremental" in flags
            try:
                runner.run(path, noincremental=noincremental)
            except Exception as e:
                log.error("Runner crashed for %s: %s", path, e)
                # Write to import-failed.log so the failure is visible in the UI,
                # not just buried in docker logs.
                runner.log_failed(path, "error")
            finally:
                try:
                    Path(config.IMPORT_ACTIVE_FILE).unlink()
                except FileNotFoundError:
                    pass
        time.sleep(5)


def _read_path_file(path_file: Path) -> tuple[str, list[str]]:
    lines = path_file.read_text().splitlines()
    path = lines[0].strip() if lines else ""
    flags = [ln.strip() for ln in lines[1:] if ln.strip()]
    return path, flags
