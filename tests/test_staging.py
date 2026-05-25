import hashlib

import pytest

import app.config as config
from app.staging import create_stage, delete_stage, stage_path


@pytest.fixture(autouse=True)
def patch_stage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IMPORT_STAGE_DIR", str(tmp_path / "import-stage"))


def test_stage_path_deterministic():
    p1 = stage_path("/media/downloads/artist/album")
    p2 = stage_path("/media/downloads/artist/album")
    assert p1 == p2


def test_stage_path_uses_sha256_prefix():
    source = "/media/downloads/artist/album"
    expected = hashlib.sha256(source.encode()).hexdigest()[:16]
    assert stage_path(source).name == expected


def test_stage_path_different_sources_differ():
    assert stage_path("/a/album1") != stage_path("/a/album2")


def test_create_stage_makes_dir():
    stage = create_stage("/media/downloads/artist/My Album")
    assert stage.is_dir()


def test_create_stage_writes_name_file():
    stage = create_stage("/media/downloads/artist/My Album")
    assert (stage / ".name").read_text(encoding="utf-8") == "My Album"


def test_create_stage_idempotent():
    source = "/media/downloads/artist/album"
    s1 = create_stage(source)
    s2 = create_stage(source)
    assert s1 == s2
    assert (s1 / ".name").exists()


def test_delete_stage_removes_dir():
    source = "/media/downloads/artist/album"
    create_stage(source)
    delete_stage(source)
    assert not stage_path(source).exists()


def test_delete_stage_noop_if_not_exists():
    delete_stage("/media/downloads/nonexistent")  # must not raise
