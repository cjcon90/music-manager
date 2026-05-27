import logging
import os
import threading
import time
from pathlib import Path

from app import config
from app.pipeline import runner
from app.queue_writer import write_queue_job

log = logging.getLogger(__name__)


def start_watcher() -> None:
    """Start the background import watcher thread (no-op if WATCHER_DISABLE is set)."""
    if os.environ.get("WATCHER_DISABLE"):
        return
    _recover_interrupted_import()
    t = threading.Thread(target=_watcher_loop, name="import-watcher", daemon=True)
    t.start()
    log.info("Import watcher started")


def _recover_interrupted_import() -> None:
    """Re-queue any import interrupted by a container restart.

    The watcher writes the current path to IMPORT_ACTIVE_FILE before calling
    runner.run() and removes it in the finally block. If the container is killed
    mid-import, that file remains. On startup we re-queue it for automatic retry.
    """
    active = Path(config.IMPORT_ACTIVE_FILE)
    if not active.exists():
        return
    path = active.read_text().strip()
    active.unlink(missing_ok=True)
    if not path:
        return
    log.warning("Detected interrupted import for %s — re-queuing", path)
    write_queue_job(path, noincremental=True, prefix="recovery")


def _watcher_loop() -> None:
    """Poll the queue directory every 5s and run runner.run() on each .path file."""
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
            move = "--move" in flags
            search_id = next(
                (f.split("=", 1)[1] for f in flags if f.startswith("--search-id=")),
                None,
            )
            try:
                runner.run(path, noincremental=noincremental, mb_id_override=search_id, move=move)
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
    """Parse a .path file into (path, flags) tuple."""
    lines = path_file.read_text().splitlines()
    path = lines[0].strip() if lines else ""
    flags = [ln.strip() for ln in lines[1:] if ln.strip()]
    return path, flags
