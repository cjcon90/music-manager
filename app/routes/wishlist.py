import datetime
import json
import re

from flask import Blueprint, redirect, render_template, request, url_for

from app import config
from app.musicbrainz import search_releases
from app.types import WishlistEntry

bp = Blueprint("wishlist", __name__)

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _read_wishlist() -> list[WishlistEntry]:
    try:
        with open(config.WISHLIST_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_wishlist(entries: list[WishlistEntry]) -> None:
    with open(config.WISHLIST_FILE, "w") as f:
        json.dump(entries, f, indent=2)


@bp.route("/wishlist")
def index() -> str:
    entries = _read_wishlist()
    return render_template(
        "wishlist.html",
        entries=list(reversed(entries)),
        candidates=[],
        searched=False,
        query="",
        artist="",
        added_ids={e["mb_id"] for e in entries},
    )


@bp.route("/wishlist/search", methods=["POST"])
def search() -> str:
    query = request.form.get("query", "").strip()
    artist = request.form.get("artist", "").strip()
    candidates = search_releases(query, artist=artist, title=query) if (query or artist) else []
    entries = _read_wishlist()
    return render_template(
        "wishlist.html",
        entries=list(reversed(entries)),
        candidates=candidates,
        searched=True,
        query=query,
        artist=artist,
        added_ids={e["mb_id"] for e in entries},
    )


@bp.route("/wishlist/add", methods=["POST"])
def add():
    mb_id = request.form.get("mb_id", "").strip()
    title = request.form.get("title", "").strip()
    artist = request.form.get("artist", "").strip()
    year = request.form.get("year", "").strip()
    if not _UUID_RE.fullmatch(mb_id):
        return redirect(url_for("wishlist.index"))
    entries = _read_wishlist()
    if not any(e["mb_id"] == mb_id for e in entries):
        entries.append(
            WishlistEntry(
                mb_id=mb_id,
                title=title,
                artist=artist,
                year=year,
                added_at=datetime.datetime.now().isoformat(),
            )
        )
        _write_wishlist(entries)
    return redirect(url_for("wishlist.index"))


@bp.route("/wishlist/remove", methods=["POST"])
def remove():
    mb_id = request.form.get("mb_id", "").strip()
    entries = [e for e in _read_wishlist() if e["mb_id"] != mb_id]
    _write_wishlist(entries)
    return redirect(url_for("wishlist.index"))
