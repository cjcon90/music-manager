import json
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

    The watcher writes the current job (path + flags, JSON) to
    IMPORT_ACTIVE_FILE before calling runner.run() and removes it in the
    finally block. If the container is killed mid-import, that file remains.
    On startup we re-queue it — with its original flags, so an interrupted
    rematch resumes as a rematch — for automatic retry.
    """
    active = Path(config.IMPORT_ACTIVE_FILE)
    if not active.exists():
        return
    raw = active.read_text().strip()
    active.unlink(missing_ok=True)
    if not raw:
        return
    try:
        info = json.loads(raw)
        path = info.get("path", "")
        noincremental = bool(info.get("noincremental", True))
        search_id = info.get("search_id")
        move = bool(info.get("move", False))
    except (json.JSONDecodeError, AttributeError):
        # Legacy plain-text format: the path alone
        path, noincremental, search_id, move = raw, True, None, False
    if not path:
        return
    log.warning("Detected interrupted import for %s — re-queuing", path)
    write_queue_job(
        path, noincremental=noincremental, search_id=search_id, move=move, prefix="recovery"
    )


def _watcher_loop() -> None:
    """Poll the queue directory every 5s and run runner.run() on each .path file."""
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
    # Ensure world-writable so qBittorrent's on-complete.sh (different container user) can write path files
    queue_dir.chmod(0o777)

    while True:
        for path_file in sorted(queue_dir.glob("*.path")):
            try:
                _process_path_file(path_file)
            except Exception as e:
                # Nothing may kill the watcher thread — the service has no way
                # to surface a dead watcher and imports would stop silently.
                # Drop the offending file so it is not retried forever.
                log.error("Watcher: dropping %s after error: %s", path_file.name, e)
                path_file.unlink(missing_ok=True)
        time.sleep(5)


def _process_path_file(path_file: Path) -> None:
    """Run one queued import job and maintain the active-job file."""
    path, flags = _read_path_file(path_file)
    # missing_ok: the queue UI's remove button may have deleted it already
    path_file.unlink(missing_ok=True)
    if not path:
        return
    noincremental = "--noincremental" in flags
    move = "--move" in flags
    search_id = next(
        (f.split("=", 1)[1] for f in flags if f.startswith("--search-id=")),
        None,
    )
    Path(config.IMPORT_ACTIVE_FILE).write_text(json.dumps({
        "path": path,
        "noincremental": noincremental,
        "search_id": search_id,
        "move": move,
    }))
    try:
        runner.run(path, noincremental=noincremental, mb_id_override=search_id, move=move)
    except Exception as e:
        log.error("Runner crashed for %s: %s", path, e)
        # Write to import-failed.log so the failure is visible in the UI,
        # not just buried in docker logs.
        runner.log_failed(path, "error")
    finally:
        Path(config.IMPORT_ACTIVE_FILE).unlink(missing_ok=True)


def _read_path_file(path_file: Path) -> tuple[str, list[str]]:
    """Parse a .path file into (path, flags) tuple."""
    lines = path_file.read_text().splitlines()
    path = lines[0].strip() if lines else ""
    flags = [ln.strip() for ln in lines[1:] if ln.strip()]
    return path, flags
