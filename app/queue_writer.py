"""Central helper for writing .path files to the import queue.

All queue consumers — routes, watcher recovery — call write_queue_job rather
than building .path files inline. This keeps the format consistent and the
queue directory permissions correct.
"""
import hashlib
import re
import time
from pathlib import Path

from app import config


def write_queue_job(
    path: str,
    *,
    noincremental: bool = True,
    search_id: str | None = None,
    move: bool = False,
    prefix: str = "job",
) -> Path:
    """Write a .path file to the import queue and return its path.

    Args:
        path: Absolute filesystem path to import.
        noincremental: Pass --noincremental to beet (re-import even if seen before).
        search_id: MusicBrainz release UUID to apply directly, skipping the matcher.
        move: Pass --move to beet (relocate files instead of copying).
        prefix: Filename prefix for human readability in the queue directory.
    """
    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
    queue_dir.chmod(0o777)  # override umask so qBittorrent (CT 104) can write

    # Validate inputs to prevent injection attacks
    if "\n" in path:
        raise ValueError(f"path must not contain newlines: {path!r}")
    if search_id is not None and not re.fullmatch(r"[0-9a-f-]{32,36}", search_id):
        raise ValueError(f"search_id must be a UUID: {search_id!r}")

    slug = re.sub(r"[^\w-]", "_", Path(path).name)[:40]
    tag = hashlib.sha256(f"{prefix}-{path}-{time.time()}".encode()).hexdigest()[:8]
    path_file = queue_dir / f"{prefix}-{tag}-{slug}.path"

    lines = [path]
    if noincremental:
        lines.append("--noincremental")
    if search_id:
        lines.append(f"--search-id={search_id}")
    if move:
        lines.append("--move")

    path_file.write_text("\n".join(lines) + "\n")
    return path_file
