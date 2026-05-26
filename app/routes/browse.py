from pathlib import Path

from flask import Blueprint, abort, render_template, request

from app import config

bp = Blueprint("browse", __name__)

_ROOTS: list[tuple[str, str]] = [
    ("Downloads", config.IMPORT_BASE_DIR),
    ("Import Stage", config.IMPORT_STAGE_DIR),
]


def _safe_resolve(raw: str) -> Path:
    """Resolve *raw* and verify it sits inside one of the allowed roots.

    Returns the resolved Path or aborts with 403.
    """
    try:
        p = Path(raw).resolve()
    except Exception:
        abort(400)
    for _label, root in _ROOTS:
        root_p = Path(root).resolve()
        if p == root_p or p.is_relative_to(root_p):
            return p
    abort(403)


def _breadcrumb(current: Path) -> list[tuple[str, str]]:
    """[(display_name, path_str), …] from the active root label down to *current*."""
    for label, root in _ROOTS:
        root_p = Path(root).resolve()
        if current == root_p or current.is_relative_to(root_p):
            crumbs: list[tuple[str, str]] = [(label, str(root_p))]
            cumulative = root_p
            for part in current.relative_to(root_p).parts:
                cumulative = cumulative / part
                crumbs.append((part, str(cumulative)))
            return crumbs
    return [(current.name, str(current))]


@bp.route("/browse")
def index() -> str:
    raw = request.args.get("path", config.IMPORT_BASE_DIR)
    current = _safe_resolve(raw)

    if not current.is_dir():
        abort(404)

    dirs: list[dict] = []
    files: list[str] = []

    try:
        for entry in sorted(
            current.iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        ):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                try:
                    children = list(entry.iterdir())
                    file_count = sum(
                        1 for c in children
                        if c.is_file() and not c.name.startswith(".")
                    )
                    subdir_count = sum(
                        1 for c in children
                        if c.is_dir() and not c.name.startswith(".")
                    )
                except OSError:
                    file_count = subdir_count = 0
                dirs.append({
                    "name": entry.name,
                    "path": str(entry),
                    "file_count": file_count,
                    "subdir_count": subdir_count,
                })
            else:
                files.append(entry.name)
    except PermissionError:
        abort(403)

    active_root = next(
        (root for _label, root in _ROOTS if str(current).startswith(root)),
        None,
    )

    return render_template(
        "browse.html",
        current=str(current),
        breadcrumb=_breadcrumb(current),
        dirs=dirs,
        files=files,
        roots=_ROOTS,
        active_root=active_root,
    )
