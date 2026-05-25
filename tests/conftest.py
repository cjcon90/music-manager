import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

os.environ["WATCHER_DISABLE"] = "1"

# Stub out beets so app.beets_api is importable without beets installed locally.
# The Library class itself is patched per-test in test_beets_api.py.
_beets_stub = MagicMock()
_beets_library_stub = MagicMock()
sys.modules.setdefault("beets", _beets_stub)
sys.modules.setdefault("beets.library", _beets_library_stub)
_beets_stub.library = _beets_library_stub

import app.beets_api  # noqa: E402 — must run after sys.modules stubs are in place

from app import create_app


@pytest.fixture
def app(tmp_path):
    import app.config as cfg

    cfg.LOCK_FILE = str(tmp_path / "manual-match.lock")
    cfg.IMPORT_QUEUE_DIR = str(tmp_path / "import-queue")
    cfg.IMPORT_FAILED_LOG = str(tmp_path / "import-failed.log")
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")
    cfg.ON_COMPLETE_LOG = str(tmp_path / "on-complete.log")
    cfg.MUSIC_LIBRARY_DIR = str(tmp_path / "music")
    if hasattr(cfg, "IMPORT_STAGE_DIR"):
        cfg.IMPORT_STAGE_DIR = str(tmp_path / "import-stage")
    (tmp_path / "import-queue").mkdir()

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def silence_flac(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "silence.flac"
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "1", "-c:a", "flac", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture(scope="session")
def windows1251_cue(tmp_path_factory):
    content = (
        'REM DATE 1961\n'
        'PERFORMER "Билли Холидей"\n'
        'TITLE "Последние записи"\n'
        'FILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n'
        '    TITLE "Я хочу тебя"\n'
        '    INDEX 01 00:00:00\n'
    )
    path = tmp_path_factory.mktemp("cue") / "windows1251.cue"
    path.write_bytes(content.encode("windows-1251"))
    return path
