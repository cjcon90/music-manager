import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.importer import ImportResult, run_beet_import


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
def test_output_combines_stdout_stderr(mock_run):
    m = MagicMock()
    m.stdout = "stdout line\n"
    m.stderr = "stderr line\n"
    m.returncode = 0
    mock_run.return_value = m
    result = run_beet_import("/stage/album", mb_id=None)
    assert "stdout line" in result.output
    assert "stderr line" in result.output
