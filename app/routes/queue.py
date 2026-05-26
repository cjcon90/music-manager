import datetime
import os
import re
import time

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app import config
from app.lock import is_locked
from app.routes.failed import read_all_failed_paths
from app.types import ActiveImport, QueuedPath

_ANSI = re.compile(r"\x1b\[[0-9;]*[mA-Za-z]")
_WATCHER_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) import-watcher: processing (.+)$")

bp = Blueprint("queue", __name__)


def _list_queued() -> list[QueuedPath]:
    try:
        result: list[QueuedPath] = []
        for fname in sorted(os.listdir(config.IMPORT_QUEUE_DIR)):
            if not fname.endswith(".path"):
                continue
            fpath = os.path.join(config.IMPORT_QUEUE_DIR, fname)
            with open(fpath) as f:
                content = f.readline().strip()
            result.append(QueuedPath(name=fname, path=content, mtime=os.path.getmtime(fpath)))
        return result
    except FileNotFoundError:
        return []


def get_active() -> ActiveImport | None:
    try:
        fpath = config.IMPORT_ACTIVE_FILE
        with open(fpath) as f:
            path = f.read().strip()
        if not path:
            return None
        return ActiveImport(path=path, since=os.path.getmtime(fpath))
    except FileNotFoundError:
        return None


def get_recently_completed(n: int = 10) -> list[dict]:
    try:
        with open(config.ON_COMPLETE_LOG) as f:
            raw = f.readlines()
    except FileNotFoundError:
        return []

    lines = [_ANSI.sub("", l).rstrip() for l in raw]

    failed_paths = read_all_failed_paths()

    entries = []
    for i, line in enumerate(lines):
        m = _WATCHER_LINE.match(line)
        if not m:
            continue
        ts_str, path = m.group(1), m.group(2).strip()
        name = os.path.basename(path)

        status = "imported"
        confirmed_match = False
        for sub in lines[i + 1 : i + 200]:
            if _WATCHER_LINE.match(sub):
                break
            if "No files imported" in sub or sub.startswith("Skipped"):
                status = "skipped"
                break
            if "WARNING: beets could not match" in sub:
                status = "failed"
                break
            if "Match (" in sub:
                confirmed_match = True
                break

        if not confirmed_match and (
            path in failed_paths
            or any(fp.startswith(path.rstrip("/") + "/") for fp in failed_paths)
        ):
            status = "failed"

        try:
            ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            ts = 0.0

        entries.append({"name": name, "path": path, "ts": ts, "status": status})

    return entries[-n:]


@bp.route("/queue")
def index() -> str:
    return render_template(
        "queue.html",
        active=get_active(),
        queued=_list_queued(),
        locked=is_locked(),
        now=time.time(),
        completed=get_recently_completed(),
    )


@bp.route("/queue/add", methods=["POST"])
def add():
    if is_locked():
        abort(409)

    path = request.form.get("path", "").strip()
    if not path:
        abort(400)
    path = path.splitlines()[0]  # prevent newline injection into .path file flags

    search_id_raw = request.form.get("search_id", "").strip()
    search_id = search_id_raw if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        search_id_raw, re.IGNORECASE,
    ) else ""

    slug = re.sub(r"[^\w-]", "_", os.path.basename(path))[:40]
    fname = f"{int(time.time())}_{slug}.path"
    os.makedirs(config.IMPORT_QUEUE_DIR, exist_ok=True)
    with open(os.path.join(config.IMPORT_QUEUE_DIR, fname), "w") as f:
        f.write(path + "\n")
        f.write("--noincremental\n")
        if search_id:
            f.write(f"--search-id={search_id}\n")

    return redirect(url_for("queue.index"))


@bp.route("/queue/remove", methods=["POST"])
def remove():
    fname = request.form.get("fname", "").strip()
    if fname and fname.endswith(".path") and "/" not in fname:
        fpath = os.path.join(config.IMPORT_QUEUE_DIR, fname)
        try:
            os.remove(fpath)
        except FileNotFoundError:
            pass
    return redirect(url_for("queue.index"))
