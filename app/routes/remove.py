from flask import Blueprint, abort, redirect, render_template, url_for

from app.beets_api import get_album_by_id
from app.pipeline.importer import run_beet_command

bp = Blueprint("remove", __name__)


@bp.route("/remove/<int:album_id>", methods=["GET"])
def confirm(album_id: int) -> str:
    album = get_album_by_id(album_id)
    if album is None:
        abort(404)
    return render_template("remove_confirm.html", album=album)


@bp.route("/remove/<int:album_id>", methods=["POST"])
def execute(album_id: int):
    album = get_album_by_id(album_id)
    if album is None:
        abort(404)
    result = run_beet_command(
        ["beet", "remove", "-d", f"album_id:{album_id}"],
        input="yes\n",
        timeout=30,
    )
    if result.returncode != 0:
        abort(500)
    return redirect(url_for("library.index"))
