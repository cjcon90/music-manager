import mimetypes
import os
import subprocess
from pathlib import Path

from flask import Blueprint, Response, jsonify, make_response, send_file

from app import config
from app.beets_api import get_album_by_id, get_album_tracks
from mutagen.flac import FLAC

bp = Blueprint("album", __name__)

_SVG_PLACEHOLDER = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
    '<rect width="48" height="48" fill="#1a1a1a" rx="3"/>'
    '<text x="24" y="31" text-anchor="middle" font-size="18" '
    'fill="#444" font-family="system-ui">♪</text>'
    '</svg>'
)


def _svg_response() -> Response:
    resp = make_response(_SVG_PLACEHOLDER)
    resp.content_type = "image/svg+xml"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/album/<int:album_id>/art")
def art(album_id: int) -> Response:
    album = get_album_by_id(album_id)
    if album and album["artpath"]:
        p = Path(album["artpath"])
        if p.exists():
            mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
            resp = send_file(p, mimetype=mime)
            resp.headers["Cache-Control"] = "no-cache"
            return resp
    return _svg_response()


@bp.route("/album/<int:album_id>/fix-art", methods=["POST"])
def fix_art(album_id: int) -> Response:
    tracks = get_album_tracks(album_id)
    if not tracks:
        return jsonify({"ok": False, "error": "Album not found or has no tracks"}), 404

    album_dir = Path(tracks[0]["path"]).parent

    for flac_path in album_dir.glob("*.flac"):
        try:
            audio = FLAC(str(flac_path))
            if audio.pictures:
                audio.clear_pictures()
                audio.save()
        except Exception as e:
            return jsonify({"ok": False, "error": f"Strip failed for {flac_path.name}: {e}"}), 500

    result = subprocess.run(
        ["beet", "fetchart", "-f", f"id:{album_id}"],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "BEETSDIR": config.BEETSDIR},
    )
    if result.returncode != 0:
        return jsonify({"ok": False, "error": result.stderr or result.stdout or "beet fetchart failed"}), 500

    return jsonify({"ok": True})
