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


from app.pipeline.runner import ImportContext, _merge_probes, _resolve_mb_id
from app.pipeline.probe import ProbeResult


def _ctx(mb_id_override=None):
    return ImportContext(
        source_path="/p", noincremental=True, mb_id_override=mb_id_override, move=False
    )


def test_merge_probes_combines_titles():
    first = ProbeResult(artist="Art", album="Alb", year="2020", track_count=2, track_titles=["A", "B"])
    result = _merge_probes(first, ["X", "Y", "Z"])
    assert result.artist == "Art"
    assert result.album == "Alb"
    assert result.year == "2020"
    assert result.track_count == 3
    assert result.track_titles == ["X", "Y", "Z"]


def test_merge_probes_handles_none_first():
    result = _merge_probes(None, ["X", "Y"])
    assert result.artist == ""
    assert result.album == ""
    assert result.track_count == 2


def test_resolve_mb_id_returns_override_without_mb_lookup():
    ctx = _ctx(mb_id_override="aaaaaaaa-0000-0000-0000-000000000000")
    probe = ProbeResult(artist="A", album="B", year="2020", track_count=5, track_titles=[])
    result = _resolve_mb_id(ctx, probe)
    assert result == "aaaaaaaa-0000-0000-0000-000000000000"


def test_resolve_mb_id_returns_none_when_no_override_and_probe_empty():
    ctx = _ctx(mb_id_override=None)
    probe = ProbeResult()
    result = _resolve_mb_id(ctx, probe)
    assert result is None


# ---------------------------------------------------------------------------
# _process_regular: CUE fallback when FLAC tags are empty
# ---------------------------------------------------------------------------

@patch("app.pipeline.runner.find_best_release", return_value="mb-whos-next")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", ""))
@patch("app.pipeline.runner.probe_cue")
@patch("app.pipeline.runner.probe_flac")
def test_regular_cue_fallback_when_flac_tags_empty(
    mock_flac, mock_cue, mock_import, mock_mb, tmp_path
):
    """When FLAC tags have no artist/album, CUE metadata fills the gap.

    Reproduces the Who's Next pattern: pre-split FLACs with zero embedded tags
    alongside a companion CUE that has PERFORMER/TITLE in its header.
    """
    # FLAC probe: no tags, but filename-derived track titles
    mock_flac.return_value = MagicMock(
        artist="", album="",
        track_count=9,
        track_titles=["01 - Baba O'Riley", "02 - Bargain", "03 - Love Ain't for Keeping"],
    )
    # CUE probe: has identity metadata
    mock_cue.return_value = MagicMock(
        artist="The Who", album="Who's Next",
        track_count=9,
        track_titles=["Baba O'Riley", "Bargain", "Love Ain't for Keeping"],
    )

    d = _make_regular(tmp_path, name="Who's Next")
    (d / "album.cue").touch()  # companion CUE exists
    run(str(d))

    # find_best_release must have been called with the CUE-supplied identity
    call_arg = mock_mb.call_args[0][0]
    assert call_arg.artist == "The Who"
    assert call_arg.album == "Who's Next"
    # but track_count and track_titles come from the FLACs
    assert call_arg.track_count == 9
    assert call_arg.track_titles == ["01 - Baba O'Riley", "02 - Bargain", "03 - Love Ain't for Keeping"]

    mock_import.assert_called_once()
    assert mock_import.call_args[1]["mb_id"] == "mb-whos-next"


@patch("app.pipeline.runner.find_best_release", return_value="mb-album")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", ""))
@patch("app.pipeline.runner.probe_cue")
@patch("app.pipeline.runner.probe_flac")
def test_regular_flac_tags_used_when_present(
    mock_flac, mock_cue, mock_import, mock_mb, tmp_path
):
    """When FLAC tags are present, CUE probe is never called."""
    mock_flac.return_value = MagicMock(
        artist="The Who", album="Quadrophenia",
        track_count=5,
        track_titles=["T1", "T2", "T3", "T4", "T5"],
    )

    d = _make_regular(tmp_path)
    run(str(d))

    mock_cue.assert_not_called()
    mock_import.assert_called_once()


# ---------------------------------------------------------------------------
# Rematch pre-remove step: beet remove before re-import
# ---------------------------------------------------------------------------

@patch("app.pipeline.runner.run_beet_command")
@patch("app.pipeline.runner.find_best_release", return_value="mb-tommy-new")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Tagging:\n  The Who - Tommy\n"))
@patch("app.pipeline.runner.probe_flac")
def test_rematch_removes_existing_db_entries_before_import(
    mock_flac, mock_import, mock_mb, mock_cmd, tmp_path
):
    """Rematch (move=True) must call beet remove before beet import.

    Without this, duplicate_action:skip causes beet to skip library files
    that are already in the database, making every rematch silently fail.
    """
    mock_flac.return_value = MagicMock(
        artist="The Who", album="Tommy",
        track_count=3, track_titles=["T1", "T2", "T3"],
    )
    mock_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")

    d = _make_regular(tmp_path, name="Tommy")
    run(str(d), move=True)

    # beet remove must have been called before beet import
    mock_cmd.assert_called_once()
    remove_cmd = mock_cmd.call_args[0][0]
    assert "remove" in remove_cmd
    assert "-f" in remove_cmd

    mock_import.assert_called_once()


@patch("app.pipeline.runner.run_beet_command")
@patch("app.pipeline.runner.find_best_release", return_value="mb-new")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("imported", "Tagging:\n  Artist - Album\n"))
@patch("app.pipeline.runner.probe_flac")
def test_normal_import_does_not_call_beet_remove(
    mock_flac, mock_import, mock_mb, mock_cmd, tmp_path
):
    """Normal (non-rematch) imports must NOT call beet remove."""
    mock_flac.return_value = MagicMock(
        artist="Artist", album="Album",
        track_count=3, track_titles=["T1", "T2", "T3"],
    )

    d = _make_regular(tmp_path)
    run(str(d), move=False)

    mock_cmd.assert_not_called()
    mock_import.assert_called_once()


@patch("app.pipeline.runner.run_beet_command")
@patch("app.pipeline.runner.run_beet_import", return_value=ImportResult("nomatch", "Skipping.\n"))
@patch("app.pipeline.runner.probe_flac")
def test_failed_rematch_restores_library_entries(mock_flac, mock_import, mock_cmd, tmp_path):
    """A rematch removes the album's DB entries before importing. If the import
    then fails, the original files must be re-imported as-is so the album does
    not silently vanish from the library."""
    mock_flac.return_value = MagicMock(
        artist="A", album="B", track_count=3, track_titles=["T1", "T2", "T3"],
    )
    d = _make_regular(tmp_path)

    run(str(d), noincremental=True, mb_id_override="mb-123", move=True)

    restore_calls = [c for c in mock_import.call_args_list if c.kwargs.get("mb_id") is None]
    assert restore_calls, "expected a restore import with mb_id=None after the failed rematch"
    assert restore_calls[-1].kwargs.get("move", False) is False
    assert restore_calls[-1].args[0] == str(d)


@patch("app.pipeline.runner.run_beet_command")
@patch(
    "app.pipeline.runner.run_beet_import",
    return_value=ImportResult("imported", "Match (98%)\n"),
)
@patch("app.pipeline.runner.probe_flac")
def test_successful_rematch_does_not_restore(mock_flac, mock_import, mock_cmd, tmp_path):
    mock_flac.return_value = MagicMock(
        artist="A", album="B", track_count=3, track_titles=["T1", "T2", "T3"],
    )
    d = _make_regular(tmp_path)

    run(str(d), noincremental=True, mb_id_override="mb-123", move=True)

    assert mock_import.call_count == 1


@patch("app.pipeline.runner.run_beet_command")
@patch("app.pipeline.runner.probe_flac")
def test_failed_rematch_logs_orphaned_when_restore_also_fails(mock_flac, mock_cmd, tmp_path):
    """If the restore import also fails, the album is truly orphaned — that must
    be visible in the failed-imports log, not buried in service logs."""
    mock_flac.return_value = MagicMock(
        artist="A", album="B", track_count=3, track_titles=["T1", "T2", "T3"],
    )
    d = _make_regular(tmp_path)

    with patch(
        "app.pipeline.runner.run_beet_import",
        return_value=ImportResult("nomatch", "Skipping.\n"),
    ):
        run(str(d), noincremental=True, mb_id_override="mb-123", move=True)

    failed_log = Path(config.IMPORT_FAILED_LOG).read_text()
    assert "rematch-orphaned" in failed_log
    assert str(d) in failed_log
