from flask import Blueprint, render_template, request

from app.beets_api import count_albums, list_albums
from app.routes.failed import count_need_attention
from app.routes.queue import get_active

bp = Blueprint("library", __name__)


@bp.route("/")
def index() -> str:
    query = request.args.get("q", "").strip()
    albums = list_albums(query)
    return render_template(
        "library.html",
        albums=albums,
        query=query,
        album_count=count_albums(),
        need_attention=count_need_attention(),
        queue_active=get_active() is not None,
    )
