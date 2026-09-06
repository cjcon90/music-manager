from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from app.beets_api import get_album_by_id
from app.pipeline.importer import BeetBusy, run_beet_command

bp = Blueprint("remove", __name__)


def _wants_json() -> bool:
    """True for the library page's fetch() call, false for the confirm form post."""
    return request.accept_mimetypes.best == "application/json"


@bp.route("/remove/<int:album_id>", methods=["GET"])
def confirm(album_id: int) -> str:
    album = get_album_by_id(album_id)
    if album is None:
        abort(404)
    return render_template("remove_confirm.html", album=album)


@bp.route("/remove/<int:album_id>", methods=["POST"])
def execute(album_id: int):
    """Delete an album. Answers JSON to the library page, a redirect to the form.

    The library page deletes in place rather than redirecting back to itself:
    re-rendering the whole library after every removal is what made deleting a
    run of albums lock up the browser.
    """
    json_wanted = _wants_json()

    album = get_album_by_id(album_id)
    if album is None:
        if json_wanted:
            return jsonify({"ok": False, "error": "Album not found"}), 404
        abort(404)

    try:
        result = run_beet_command(
            ["beet", "remove", "-d", f"album_id:{album_id}"],
            input="yes\n",
            timeout=30,
        )
    except BeetBusy:
        msg = "An import is running — try again in a moment."
        if json_wanted:
            return jsonify({"ok": False, "error": msg}), 503
        abort(503, msg)

    if result.returncode != 0:
        if json_wanted:
            error = result.stderr or result.stdout or "beet remove failed"
            return jsonify({"ok": False, "error": error}), 500
        abort(500)

    if json_wanted:
        return jsonify({"ok": True})
    return redirect(url_for("library.index"))
