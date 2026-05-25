import os
import subprocess

from flask import Blueprint, abort, redirect, render_template, url_for

from app import config
from app.beets_api import get_album_by_id

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
    result = subprocess.run(
        ["beet", "remove", "-d", f"album_id:{album_id}"],
        input="yes\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "BEETSDIR": config.BEETSDIR},
    )
    if result.returncode != 0:
        abort(500)
    return redirect(url_for("library.index"))
