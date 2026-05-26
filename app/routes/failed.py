import fcntl
import os
import uuid

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app import config
from app.lock import is_locked
from app.types import FailedEntry

bp = Blueprint("failed", __name__)


def _display_name(path: str) -> str:
    clean = path.rstrip("/")
    if os.path.basename(clean) == ".beet-stage":
        clean = os.path.dirname(clean)
    base = config.IMPORT_BASE_DIR.rstrip("/")
    if clean.startswith(base + "/"):
        clean = clean[len(base) + 1:]
    return clean.replace("/", " › ")


def _read_dismissed() -> set[str]:
    try:
        with open(config.IMPORT_FAILED_DISMISSED_LOG) as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def _read_failed() -> list[FailedEntry]:
    try:
        with open(config.IMPORT_FAILED_LOG) as f:
            lines = [line.rstrip() for line in f if line.strip()]
    except FileNotFoundError:
        return []
    dismissed = _read_dismissed()
    result: list[FailedEntry] = []
    for line in lines:
        parts = line.split(" | ", 2)
        if len(parts) == 3:
            ts, kind, path = parts[0].strip(), parts[1].strip(), parts[2].strip()
        elif len(parts) == 2:
            ts, path = parts[0].strip(), parts[1].strip()
            kind = "nomatch"
        else:
            continue
        if line in dismissed:
            continue
        result.append(FailedEntry(ts=ts, path=path, name=_display_name(path), kind=kind, line=line))
    return result


def count_need_attention() -> int:
    return len(_read_failed())


def read_all_failed_paths() -> set[str]:
    """Return all paths from the failed log regardless of dismissed state."""
    try:
        with open(config.IMPORT_FAILED_LOG) as f:
            lines = [line.rstrip() for line in f if line.strip()]
    except FileNotFoundError:
        return set()
    paths: set[str] = set()
    for line in lines:
        parts = line.split(" | ", 2)
        if len(parts) == 3:
            paths.add(parts[2].strip())
        elif len(parts) == 2:
            paths.add(parts[1].strip())
    return paths


def _dismiss_line(line: str) -> None:
    with open(config.IMPORT_FAILED_DISMISSED_LOG, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


@bp.route("/failed")
def index() -> str:
    filter_type = request.args.get("type", "all")
    all_entries = _read_failed()
    counts = {
        "all": len(all_entries),
        "nomatch": sum(1 for e in all_entries if e["kind"] == "nomatch"),
        "skipped": sum(1 for e in all_entries if e["kind"] == "skipped"),
        "error": sum(1 for e in all_entries if e["kind"] == "error"),
    }
    if filter_type in ("nomatch", "skipped", "error"):
        entries = [e for e in all_entries if e["kind"] == filter_type]
    else:
        entries = all_entries
    return render_template(
        "failed.html", entries=entries, counts=counts, active_filter=filter_type
    )


@bp.route("/failed/dismiss", methods=["POST"])
def dismiss():
    line = request.form.get("line", "").strip()
    if line:
        _dismiss_line(line)
    return redirect(url_for("failed.index"))


@bp.route("/failed/requeue", methods=["POST"])
def requeue():
    if is_locked():
        abort(409)
    path = request.form.get("path", "").strip()
    line = request.form.get("line", "").strip()
    if path:
        fname = uuid.uuid4().hex[:10] + ".path"
        fpath = os.path.join(config.IMPORT_QUEUE_DIR, fname)
        with open(fpath, "w") as f:
            f.write(path + "\n")
            f.write("--noincremental\n")
        if line:
            _dismiss_line(line)
    return redirect(url_for("failed.index"))


def dismiss_failed_entry(path: str) -> None:
    """Dismiss all failed-import entries matching *path*. Called programmatically."""
    if not path:
        return
    try:
        with open(config.IMPORT_FAILED_LOG) as f:
            lines = [line.rstrip() for line in f if line.strip()]
    except FileNotFoundError:
        return
    for line in lines:
        parts = line.split(" | ", 2)
        line_path = (parts[2] if len(parts) == 3 else parts[1] if len(parts) == 2 else "").strip()
        if line_path == path:
            _dismiss_line(line)


@bp.route("/failed/dismiss-by-path", methods=["POST"])
def dismiss_by_path():
    """Dismiss the failed-import entry matching a given stage_path.

    Called automatically by the manual-match UI after a successful import so the
    album disappears from Failed Imports without the user having to click dismiss.
    Returns 204 in all cases (no match is not an error).
    """
    path = request.form.get("path", "").strip()
    if not path:
        return "", 204
    try:
        with open(config.IMPORT_FAILED_LOG) as f:
            lines = [line.rstrip() for line in f if line.strip()]
    except FileNotFoundError:
        return "", 204
    for line in lines:
        parts = line.split(" | ", 2)
        line_path = (parts[2] if len(parts) == 3 else parts[1] if len(parts) == 2 else "").strip()
        if line_path == path:
            _dismiss_line(line)
            break
    return "", 204
