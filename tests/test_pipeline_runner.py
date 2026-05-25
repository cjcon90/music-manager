from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import app.config as config
from app.pipeline.importer import ImportResult
from app.pipeline.runner import run


@pytest.fixture(autouse=True)
def patch_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ON_COMPLETE_LOG", str(tmp_path / "on-complete.log"))
    monkeypatch.setattr(config, "IMPORT_FAILED_LOG", str(tmp_path / "import-failed.log"))
    monkeypatch.setattr(config, "IMPORT_STAGE_DIR", str(tmp_path / "import-stage"))


def _make_regular(tmp_path: Path, name: str = "album") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (d / f"{i+1:02d}.flac").touch()
    return d


def _make_cue(tmp_path: Path, name: str = "album") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "album.flac").touch()
    (d / "album.cue").touch()
    return d


@patch("app.pipeline.runner.find_best_release", return_value="mb-123")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Match (98%)\n"))
@patch("app.pipeline.runner.probe_flac")
def test_run_regular_match(mock_probe, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(artist="A", album="B", track_count=3, track_titles=["T1", "T2", "T3"])
    d = _make_regular(tmp_path)
    run(str(d))
    mock_import.assert_called_once()
    args = mock_import.call_args
    assert args[1]["mb_id"] == "mb-123"


@patch("app.pipeline.runner.find_best_release", return_value=None)
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", ""))
@patch("app.pipeline.runner.probe_flac")
def test_run_regular_no_match_uses_noautotag(mock_probe, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(artist="A", album="B", track_count=3, track_titles=[])
    d = _make_regular(tmp_path)
    run(str(d))
    args = mock_import.call_args
    assert args[1]["mb_id"] is None


@patch("app.pipeline.runner.find_best_release", return_value="mb-123")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Match (95%)\n"))
@patch("app.pipeline.runner.split_cue_rip")
@patch("app.pipeline.runner.probe_cue")
def test_run_cue_match_deletes_stage(mock_probe, mock_split, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(
        artist="A", album="B", track_count=2,
        track_titles=["T1", "T2"], timings=[0.0, 60.0], source_file=Path("/src/file.flac"),
    )
    d = _make_cue(tmp_path)
    run(str(d))
    # Stage dir should not exist (deleted after import)
    from app.staging import stage_path
    assert not stage_path(str(d)).exists()


@patch("app.pipeline.runner.find_best_release", return_value=None)
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("nomatch", "Skipping.\n"))
@patch("app.pipeline.runner.split_cue_rip")
@patch("app.pipeline.runner.probe_cue")
def test_run_cue_nomatch_preserves_stage(mock_probe, mock_split, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(
        artist="A", album="B", track_count=2,
        track_titles=["T1", "T2"], timings=[0.0, 60.0], source_file=Path("/src/file.flac"),
    )
    d = _make_cue(tmp_path)
    run(str(d))
    from app.staging import stage_path, create_stage
    create_stage(str(d))  # recreate to check file system state
    # import-failed.log should have an entry
    log = (tmp_path / "import-failed.log").read_text()
    assert "nomatch" in log
    assert str(d) in log


@patch("app.pipeline.runner.find_best_release", return_value="mb-123")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Match (95%)\n"))
@patch("app.pipeline.runner.split_cue_rip")
@patch("app.pipeline.runner.probe_cue")
def test_run_cue_reuses_existing_split(mock_probe, mock_split, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(
        artist="A", album="B", track_count=2,
        track_titles=["T1", "T2"], timings=[0.0, 60.0], source_file=Path("/src/file.flac"),
    )
    d = _make_cue(tmp_path)
    # Pre-populate stage with a FLAC file
    from app import staging
    stage = staging.create_stage(str(d))
    (stage / "01 - T1.flac").touch()
    run(str(d))
    mock_split.assert_not_called()


@patch("app.pipeline.runner.split_cue_rip", side_effect=RuntimeError("encode error"))
@patch("app.pipeline.runner.probe_cue")
def test_run_cue_split_failure_logs_skipped(mock_probe, mock_split, tmp_path):
    mock_probe.return_value = MagicMock(
        artist="A", album="B", track_count=2,
        track_titles=["T1"], timings=[0.0], source_file=Path("/src/file.flac"),
    )
    d = _make_cue(tmp_path)
    run(str(d))
    log = (tmp_path / "import-failed.log").read_text()
    assert "skipped" in log


@patch("app.pipeline.runner.find_best_release", return_value="mb-123")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Match\n"))
@patch("app.pipeline.runner.probe_flac")
def test_run_discography_processes_all_albums(mock_probe, mock_import, mock_mb, tmp_path):
    mock_probe.return_value = MagicMock(artist="A", album="B", track_count=3, track_titles=[])
    root = tmp_path / "discography"
    for name in ["1990-album1", "1995-album2", "2000-album3"]:
        for i in range(3):
            (root / name).mkdir(parents=True, exist_ok=True)
            (root / name / f"{i+1:02d}.flac").touch()
    run(str(root))
    assert mock_import.call_count == 3


def test_run_empty_dir_logs_skipped(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    run(str(d))
    log = (tmp_path / "import-failed.log").read_text()
    assert "skipped" in log


def test_run_writes_processing_line(tmp_path):
    d = _make_regular(tmp_path)
    with patch("app.pipeline.runner.find_best_release", return_value=None), \
         patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "")), \
         patch("app.pipeline.runner.probe_flac", return_value=MagicMock(artist="A", album="B", track_count=3, track_titles=[])):
        run(str(d))
    log = (tmp_path / "on-complete.log").read_text()
    assert "import-watcher: processing" in log
    assert str(d) in log
