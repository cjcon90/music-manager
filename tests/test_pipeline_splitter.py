import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.probe import ProbeResult
from app.pipeline.splitter import split_cue_rip

SIMPLE_PROBE = ProbeResult(
    artist="Billie Holiday",
    album="Lady in Satin",
    year="1958",
    track_count=2,
    track_titles=["Track One", "Track Two"],
    timings=[0.0, 60.0],
    disc_number=None,
)

PROBE_WITH_DISC = ProbeResult(
    artist="Artist",
    album="Double Album",
    year="2000",
    track_count=2,
    track_titles=["Track One", "Track Two"],
    timings=[0.0, 60.0],
    disc_number=1,
)


@patch("app.pipeline.splitter.subprocess.run")
def test_split_flac_calls_flac_cli(mock_run, tmp_path, silence_flac):
    mock_run.return_value = MagicMock(returncode=0)
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
    split_cue_rip(tmp_path, tmp_path / "stage", probe)
    assert mock_run.call_count == 2
    first_cmd = mock_run.call_args_list[0][0][0]
    assert first_cmd[0] == "flac"


@patch("app.pipeline.splitter.subprocess.run")
def test_split_flac_embeds_tags(mock_run, tmp_path, silence_flac):
    mock_run.return_value = MagicMock(returncode=0)
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
    split_cue_rip(tmp_path, tmp_path / "stage", probe)
    first_cmd = mock_run.call_args_list[0][0][0]
    assert "--tag=TITLE=Track One" in first_cmd
    assert "--tag=TRACKNUMBER=1" in first_cmd
    assert "--tag=TRACKTOTAL=2" in first_cmd
    assert "--tag=ARTIST=Billie Holiday" in first_cmd
    assert "--tag=ALBUM=Lady in Satin" in first_cmd
    assert "--tag=DATE=1958" in first_cmd


@patch("app.pipeline.splitter.subprocess.run")
def test_split_flac_embeds_discnumber(mock_run, tmp_path, silence_flac):
    mock_run.return_value = MagicMock(returncode=0)
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**PROBE_WITH_DISC.__dict__, "source_file": src})
    split_cue_rip(tmp_path, tmp_path / "stage", probe)
    first_cmd = mock_run.call_args_list[0][0][0]
    assert "--tag=DISCNUMBER=1" in first_cmd


@patch("app.pipeline.splitter.subprocess.run")
def test_split_flac_skip_until_timing(mock_run, tmp_path, silence_flac):
    mock_run.return_value = MagicMock(returncode=0)
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
    split_cue_rip(tmp_path, tmp_path / "stage", probe)
    cmds = [c[0][0] for c in mock_run.call_args_list]
    # Track 1: has --until (not last track)
    assert any("--until=1:00.000" in arg for arg in cmds[0])
    # Track 2 (last): no --until
    assert not any("--until" in arg for arg in cmds[1])


@patch("app.pipeline.splitter.subprocess.run")
def test_split_ape_calls_ffmpeg(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    src = tmp_path / "source.ape"
    src.touch()
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
    split_cue_rip(tmp_path, tmp_path / "stage", probe)
    first_cmd = mock_run.call_args_list[0][0][0]
    assert first_cmd[0] == "ffmpeg"


@patch("app.pipeline.splitter.subprocess.run")
def test_split_flac_failure_raises(mock_run, tmp_path, silence_flac):
    mock_run.return_value = MagicMock(returncode=1, stderr=b"encode error")
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
    with pytest.raises(RuntimeError, match="flac failed"):
        split_cue_rip(tmp_path, tmp_path / "stage", probe)


def test_split_no_source_file_raises(tmp_path):
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": None})
    with pytest.raises(FileNotFoundError):
        split_cue_rip(tmp_path, tmp_path / "stage", probe)


def test_split_no_timings_raises(tmp_path, silence_flac):
    src = tmp_path / "source.flac"
    shutil.copy(silence_flac, src)
    probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src, "timings": None})
    with pytest.raises(ValueError):
        split_cue_rip(tmp_path, tmp_path / "stage", probe)


def test_split_creates_stage_dir(tmp_path, silence_flac):
    with patch("app.pipeline.splitter.subprocess.run", return_value=MagicMock(returncode=0)):
        src = tmp_path / "source.flac"
        shutil.copy(silence_flac, src)
        probe = ProbeResult(**{**SIMPLE_PROBE.__dict__, "source_file": src})
        stage = tmp_path / "stage"
        split_cue_rip(tmp_path, stage, probe)
        assert stage.is_dir()
