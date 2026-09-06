"""On-disk thumbnail cache for album cover art.

The library page renders one 48px <img> per album. Serving the originals cost
~300 KB each — 291 MB across 959 albums — to paint a 48x48 box, which is what
made the page slow to load and Chrome slow to respond. A cached 96px WebP is
~4 KB, so the same page costs single-digit MB even with a cold cache.

Thumbnails are keyed on the source file's mtime, so replacing a cover (Fix Art,
or beets re-fetching one) yields a new cache file instead of needing explicit
invalidation.
"""

import logging
import os
import uuid
from pathlib import Path

from PIL import Image

from app import config

log = logging.getLogger(__name__)

# Twice the 48px the template displays, so HiDPI screens still look sharp.
THUMB_SIZE = 96
THUMB_QUALITY = 80


def thumb_dir() -> Path:
    """Cache directory. Read from config at call time so tests can redirect it."""
    return Path(config.BEETSDIR) / "thumbs"


def get_thumb(album_id: int, source: Path) -> Path | None:
    """Return a cached 96px WebP of *source*, rendering it on first request.

    Returns None when the source is missing, unreadable or undecodable, so the
    caller can fall back to the placeholder rather than erroring.
    """
    try:
        mtime = int(source.stat().st_mtime)
    except OSError:
        return None

    dest = thumb_dir() / f"{album_id}-{mtime}.webp"
    if dest.exists():
        return dest

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as opened:
            # thumbnail() drafts the JPEG decode down to roughly the target size,
            # so a 1200px cover is never fully decoded just to produce 96px.
            opened.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            im = opened if opened.mode in ("RGB", "RGBA") else opened.convert("RGB")
            # Write to a unique temp name and rename: concurrent requests for the
            # same album must never observe a half-written file.
            tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.tmp")
            try:
                im.save(tmp, "WEBP", quality=THUMB_QUALITY, method=4)
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Thumbnail generation failed for %s: %s", source, e)
        return None

    _drop_stale(album_id, dest)
    return dest


def _drop_stale(album_id: int, keep: Path) -> None:
    """Delete this album's older thumbnails so replaced covers don't accumulate."""
    try:
        for old in thumb_dir().glob(f"{album_id}-*.webp"):
            if old != keep:
                old.unlink(missing_ok=True)
    except OSError:
        pass
