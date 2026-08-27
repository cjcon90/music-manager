from flask import Blueprint, render_template, request

from app.beets_api import (
    NO_MBID_QUERY,
    count_albums,
    count_albums_without_mbid,
    list_albums,
)
from app.routes.failed import count_need_attention
from app.routes.queue import get_active

bp = Blueprint("library", __name__)


@bp.route("/")
def index() -> str:
    query = request.args.get("q", "").strip()
    no_mb = request.args.get("filter") == "no-mb"
    # beets ANDs whitespace-separated terms, so the filter composes with a search.
    effective_query = f"{query} {NO_MBID_QUERY}".strip() if no_mb else query
    albums = list_albums(effective_query)
    return render_template(
        "library.html",
        albums=albums,
        query=query,
        no_mb=no_mb,
        album_count=count_albums(),
        no_mb_count=count_albums_without_mbid(),
        need_attention=count_need_attention(),
        queue_active=get_active() is not None,
    )
