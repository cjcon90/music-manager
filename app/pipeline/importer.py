import logging
import os
import subprocess
import threading
from dataclasses import dataclass

from app.config import BEETSDIR

log = logging.getLogger(__name__)

# Serialise all beet invocations — beet's SQLite DB does not tolerate concurrent writers
_beet_lock = threading.Lock()

# Config overlay applied whenever the user has explicitly chosen an MB release ID.
# Sets strong_rec_thresh: 1.0 so beet auto-applies the match regardless of
# track-length differences between pressings. The user already made the call.
_MB_ID_CONFIG = os.path.join(BEETSDIR, "rematch-config.yaml")


def run_beet_command(
    cmd: list[str],
    *,
    timeout: int = 60,
    input: str | None = None,
) -> subprocess.CompletedProcess:
    """Run an arbitrary beet subcommand under the serialisation lock.

    Use this for any beet call outside the main import path (e.g. fetchart,
    remove) so all beet processes share the same SQLite-write lock and avoid
    database corruption from concurrent writes.
    """
    with _beet_lock:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
            env={**os.environ, "BEETSDIR": BEETSDIR},
        )


@dataclass
class ImportResult:
    """Return value from run_beet_import. status is one of: imported | nomatch | duplicate | timeout."""

    status: str  # "imported" | "nomatch" | "duplicate" | "timeout"
    output: str


def run_beet_import(
    path: str,
    mb_id: str | None,
    noincremental: bool = True,
    move: bool = False,
) -> ImportResult:
    """Run beet import under the serialisation lock; return a structured ImportResult.

    When mb_id is set the user has explicitly chosen the release — bypass beet's
    quality threshold by loading the rematch config overlay (strong_rec_thresh: 1.0).
    Automatic imports (mb_id=None) use the standard config thresholds.
    """
    cmd = ["beet"]
    if mb_id:
        # User-selected release: accept any match distance.
        cmd += ["-c", _MB_ID_CONFIG]
    cmd += ["import", "--quiet"]
    if noincremental:
        cmd.append("--noincremental")
    if move:
        cmd.append("--move")
    if mb_id:
        cmd += ["--search-id", mb_id]
    else:
        cmd.append("--noautotag")
    cmd.append(path)

    with _beet_lock:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=21600,
                env={**os.environ, "BEETSDIR": BEETSDIR},
            )
        except subprocess.TimeoutExpired:
            return ImportResult(status="timeout", output="")

    output = result.stdout + result.stderr

    if result.returncode != 0:
        msg = output.strip() or "[no output]"
        log.error("beet exited %d for %s: %s", result.returncode, path, msg)
        return ImportResult(
            status="nomatch",
            output=f"[beet error — exit {result.returncode}]\n{output}",
        )

    if "Skipping." in output:
        return ImportResult(status="nomatch", output=output)
    if "No files imported" in output:
        return ImportResult(status="duplicate", output=output)

    if not output.strip():
        log.error("beet silent failure for %s — no output produced", path)
        return ImportResult(
            status="nomatch",
            output="[beet silent failure — no output]",
        )

    return ImportResult(status="imported", output=output)
