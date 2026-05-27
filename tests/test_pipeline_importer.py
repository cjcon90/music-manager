import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.importer import ImportResult, _MB_ID_CONFIG, run_beet_command, run_beet_import


def _mock_run(stdout: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


@patch("app.pipeline.importer.subprocess.run")
def test_search_id_success(mock_run):
    mock_run.return_value = _mock_run("Importing /stage/album\nMatch (98.1%)\n")
    result = run_beet_import("/stage/album", mb_id="mb-123")
    assert result.status == "imported"
    cmd = mock_run.call_args[0][0]
    assert "--search-id" in cmd
    assert "mb-123" in cmd
    assert "--noautotag" not in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_search_id_skip(mock_run):
    mock_run.return_value = _mock_run("Skipping.\n")
    result = run_beet_import("/stage/album", mb_id="mb-123")
    assert result.status == "nomatch"


@patch("app.pipeline.importer.subprocess.run")
def test_noautotag_success(mock_run):
    mock_run.return_value = _mock_run("/stage/album -> /media/music/Artist/Album\n")
    result = run_beet_import("/stage/album", mb_id=None)
    assert result.status == "imported"
    cmd = mock_run.call_args[0][0]
    assert "--noautotag" in cmd
    assert "--search-id" not in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_duplicate(mock_run):
    mock_run.return_value = _mock_run("No files imported\n")
    result = run_beet_import("/stage/album", mb_id=None)
    assert result.status == "duplicate"


@patch("app.pipeline.importer.subprocess.run")
def test_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="beet", timeout=21600)
    result = run_beet_import("/stage/album", mb_id=None)
    assert result.status == "timeout"
    assert result.output == ""


@patch("app.pipeline.importer.subprocess.run")
def test_noincremental_flag(mock_run):
    mock_run.return_value = _mock_run("")
    run_beet_import("/stage/album", mb_id=None, noincremental=True)
    cmd = mock_run.call_args[0][0]
    assert "--noincremental" in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_no_noincremental_flag(mock_run):
    mock_run.return_value = _mock_run("")
    run_beet_import("/stage/album", mb_id=None, noincremental=False)
    cmd = mock_run.call_args[0][0]
    assert "--noincremental" not in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_move_rematch_success(mock_run):
    """--move rematch: beet outputs the destination path, not the source.

    This was the bug: the old `path not in output` check classified every
    successful move-rematch as a silent failure because beet's output only
    references the new library path after relocation.
    """
    mock_run.return_value = _mock_run(
        "Tagging:\n    The Who - Tommy\n(Similarity: 99.7%) (ID: cc6adf85) The Who - Tommy\nMoving 1 items\n"
    )
    result = run_beet_import("/data/music/The Who/Tommy (1996)", mb_id="cc6adf85", move=True)
    assert result.status == "imported"
    cmd = mock_run.call_args[0][0]
    assert "--move" in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_mb_id_uses_config_overlay(mock_run):
    """Any explicit mb_id — downloads or library — must load the config overlay.

    Manual match is authoritative: the user identified the release, so beet must
    apply it regardless of track-length distance between pressings.
    """
    mock_run.return_value = _mock_run("Importing /stage/album\n")
    run_beet_import("/stage/album", mb_id="abc-123", move=False)
    cmd = mock_run.call_args[0][0]
    assert "-c" in cmd
    assert _MB_ID_CONFIG in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_mb_id_uses_config_overlay_on_rematch(mock_run):
    """Library rematch (move=True + mb_id) also loads the config overlay."""
    mock_run.return_value = _mock_run("Moving 1 items\n")
    run_beet_import("/data/music/The Who/Tommy (1996)", mb_id="abc-123", move=True)
    cmd = mock_run.call_args[0][0]
    assert "-c" in cmd
    assert _MB_ID_CONFIG in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_no_mb_id_does_not_use_config_overlay(mock_run):
    """Automatic imports (mb_id=None) must NOT load the config overlay."""
    mock_run.return_value = _mock_run("Importing /stage/album\n")
    run_beet_import("/stage/album", mb_id=None, move=False)
    cmd = mock_run.call_args[0][0]
    assert "-c" not in cmd


@patch("app.pipeline.importer.subprocess.run")
def test_silent_failure_no_output(mock_run):
    """Beet exits 0 but produces empty output — silent crash, must be nomatch."""
    mock_run.return_value = _mock_run("")
    result = run_beet_import("/stage/album", mb_id="mb-123")
    assert result.status == "nomatch"


@patch("app.pipeline.importer.subprocess.run")
def test_output_combines_stdout_stderr(mock_run):
    m = MagicMock()
    m.stdout = "Tagging:\n    Artist - Album\n"
    m.stderr = "some warning\n"
    m.returncode = 0
    mock_run.return_value = m
    result = run_beet_import("/stage/album", mb_id=None)
    assert result.status == "imported"
    assert "Tagging" in result.output
    assert "some warning" in result.output


@patch("app.pipeline.importer.subprocess.run")
def test_run_beet_command_sets_beetsdir(mock_run):
    """run_beet_command must set BEETSDIR in the subprocess environment."""
    mock_run.return_value = MagicMock(returncode=0)
    run_beet_command(["beet", "fetchart"])
    call_kwargs = mock_run.call_args.kwargs
    assert "BEETSDIR" in call_kwargs["env"]


@patch("app.pipeline.importer.subprocess.run")
def test_run_beet_command_accepts_input(mock_run):
    """run_beet_command must pass the input kwarg to subprocess."""
    mock_run.return_value = MagicMock(returncode=0)
    run_beet_command(["beet", "remove", "-d", "id:1"], input="yes\n")
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("input") == "yes\n"
