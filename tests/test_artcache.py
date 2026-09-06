import os

import pytest
from PIL import Image

from app import artcache


@pytest.fixture
def beetsdir(tmp_path, monkeypatch):
    """Point the thumbnail cache at a temp dir for the duration of a test."""
    monkeypatch.setattr(artcache.config, "BEETSDIR", str(tmp_path))
    return tmp_path


def _make_cover(path, size=(1200, 1200), colour=(200, 30, 30), fmt="JPEG"):
    Image.new("RGB", size, colour).save(path, fmt)
    return path


def test_returns_none_when_source_missing(beetsdir, tmp_path):
    assert artcache.get_thumb(1, tmp_path / "nope.jpg") is None


def test_returns_none_when_source_is_not_an_image(beetsdir, tmp_path):
    junk = tmp_path / "cover.jpg"
    junk.write_bytes(b"\xff\xd8\xff\xe0not actually a jpeg")
    assert artcache.get_thumb(1, junk) is None


def test_generates_webp_thumbnail(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")

    thumb = artcache.get_thumb(7, cover)

    assert thumb is not None and thumb.exists()
    assert thumb.suffix == ".webp"
    with Image.open(thumb) as im:
        assert im.format == "WEBP"
        assert max(im.size) == artcache.THUMB_SIZE


def test_thumbnail_is_far_smaller_than_the_original(beetsdir, tmp_path):
    # Photographic noise, so the JPEG does not compress to near-nothing and the
    # size comparison is meaningful.
    src = Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3))
    cover = tmp_path / "cover.jpg"
    src.save(cover, "JPEG", quality=95)

    thumb = artcache.get_thumb(1, cover)

    assert thumb.stat().st_size < cover.stat().st_size / 10


def test_second_call_reuses_the_cached_file(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")

    first = artcache.get_thumb(3, cover)
    stamp = first.stat().st_mtime_ns
    second = artcache.get_thumb(3, cover)

    assert second == first
    assert second.stat().st_mtime_ns == stamp  # not re-rendered


def test_new_source_mtime_produces_a_new_thumbnail(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")
    first = artcache.get_thumb(4, cover)

    _make_cover(cover, colour=(20, 20, 200))
    os.utime(cover, (0, 0))  # deterministic, definitely different mtime
    second = artcache.get_thumb(4, cover)

    assert second != first


def test_replacing_art_does_not_leave_stale_thumbnails(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")
    artcache.get_thumb(5, cover)

    os.utime(cover, (0, 0))
    kept = artcache.get_thumb(5, cover)

    assert list(artcache.thumb_dir().glob("5-*.webp")) == [kept]


def test_thumbnails_for_different_albums_coexist(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")

    a = artcache.get_thumb(1, cover)
    b = artcache.get_thumb(12, cover)

    assert a != b
    assert a.exists() and b.exists()


def test_no_temp_files_are_left_behind(beetsdir, tmp_path):
    cover = _make_cover(tmp_path / "cover.jpg")
    artcache.get_thumb(9, cover)

    assert list(artcache.thumb_dir().glob("*.tmp")) == []


def test_palette_image_is_converted(beetsdir, tmp_path):
    cover = tmp_path / "cover.png"
    Image.new("P", (300, 300)).save(cover, "PNG")

    thumb = artcache.get_thumb(11, cover)

    assert thumb is not None and thumb.exists()
