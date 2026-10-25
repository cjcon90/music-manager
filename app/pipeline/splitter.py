import re
import subprocess
from pathlib import Path

from app.pipeline.probe import ProbeResult, probe_cue

# Leading bytes of every format in AUDIO_EXTS. An ISO 9660 image renamed .wv
# (Comus, Pentangle) starts with zeros and matches none of them.
_AUDIO_MAGIC = (
    b"fLaC", b"wvpk", b"MAC ", b"RIFF", b"RF64", b"OggS", b"FORM", b"DSD ", b"FRM8", b"ID3",
)


class SplitCheckError(Exception):
    """The source can't be split as the sheet describes; *kind* goes to the failed log."""
    kind = "split-failed"


class NotAudioError(SplitCheckError):
    kind = "not-audio"


class CueMismatchError(SplitCheckError):
    kind = "cue-mismatch"


def check_split_source(probe: ProbeResult) -> None:
    """Refuse a split that would produce garbage, truncated or empty tracks.

    A missing source is left for split_cue_rip to report.
    """
    src = probe.source_file
    if src is None or not src.exists():
        return
    with open(src, "rb") as f:
        head = f.read(12)
    is_mp3 = len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    if not (head.startswith(_AUDIO_MAGIC) or head[4:8] == b"ftyp" or is_mp3):
        raise NotAudioError(f"{src.name} is not audio — redownload from a different source")
    timings = probe.timings
    if not timings or not 1 <= len(timings) <= 99 or len(timings) != probe.track_count:
        raise CueMismatchError(f"sheet has {probe.track_count} tracks, INDEX 01 times incomplete")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=300,
    )
    duration = float(result.stdout.strip())
    if timings[-1] >= duration:
        raise CueMismatchError(
            f"last track starts at {timings[-1]:.0f}s but {src.name} is {duration:.0f}s long"
        )


def split_cue_rip(source_dir: Path, stage_dir: Path, probe: ProbeResult | None = None) -> None:
    """Split a single audio file into individual tracks using CUE timings, writing to stage_dir."""
    if probe is None:
        probe = probe_cue(source_dir)

    if not probe.source_file or not probe.source_file.exists():
        raise FileNotFoundError(f"Audio source not found in {source_dir}")
    if not probe.timings or len(probe.timings) != probe.track_count:
        raise ValueError(f"Missing or incomplete timings for CUE rip in {source_dir}")

    stage_dir.mkdir(parents=True, exist_ok=True)
    audio = probe.source_file
    is_flac = audio.suffix.lower() == ".flac"

    for i, (title, start) in enumerate(zip(probe.track_titles, probe.timings)):
        # Use explicit CUE TRACK numbers when available (set by probe_multi_file_cue
        # so that globally-numbered tracks like 7–12 on Side B are not reset to 1–6).
        num = probe.track_numbers[i] if probe.track_numbers else i + 1
        end = probe.timings[i + 1] if i + 1 < len(probe.timings) else None
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip()
        out = stage_dir / f"{num:02d} - {safe}.flac"
        if is_flac:
            _split_flac(audio, out, start, end, num, probe, title)
        else:
            _split_ffmpeg(audio, out, start, end, num, probe, title)


def _t(secs: float) -> str:
    return f"{int(secs // 60)}:{secs % 60:06.3f}"


def _split_flac(
    src: Path, out: Path, start: float, end: float | None,
    num: int, probe: ProbeResult, title: str,
) -> None:
    """Split a FLAC source using the native flac CLI for lossless re-encoding."""
    cmd = ["flac", "--silent", "--force"]
    if start:
        cmd.append(f"--skip={_t(start)}")
    if end is not None:
        cmd.append(f"--until={_t(end)}")
    cmd += [
        f"--tag=TITLE={title}",
        f"--tag=TRACKNUMBER={num}",
        f"--tag=TRACKTOTAL={probe.track_count}",
        f"--tag=ARTIST={probe.artist}",
        f"--tag=ALBUM={probe.album}",
    ]
    if probe.year:
        cmd.append(f"--tag=DATE={probe.year}")
    if probe.disc_number is not None:
        cmd.append(f"--tag=DISCNUMBER={probe.disc_number}")
    cmd += ["-o", str(out), str(src)]
    result = subprocess.run(cmd, capture_output=True, timeout=3600)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")[-200:]
        raise RuntimeError(f"flac failed for track {num}: {err}")


def _split_ffmpeg(
    src: Path, out: Path, start: float, end: float | None,
    num: int, probe: ProbeResult, title: str,
) -> None:
    """Split a non-FLAC source (e.g. WAV, APE) via ffmpeg, encoding output as FLAC."""
    cmd = ["ffmpeg", "-ss", f"{start:.6f}", "-i", str(src)]
    if end is not None:
        cmd += ["-to", f"{end - start:.6f}"]
    cmd += [
        "-c:a", "flac", "-map_metadata", "-1",
        "-metadata", f"title={title}",
        "-metadata", f"tracknumber={num}",
        "-metadata", f"tracktotal={probe.track_count}",
        "-metadata", f"artist={probe.artist}",
        "-metadata", f"album={probe.album}",
    ]
    if probe.year:
        cmd += ["-metadata", f"date={probe.year}"]
    if probe.disc_number is not None:
        cmd += ["-metadata", f"discnumber={probe.disc_number}"]
    cmd += ["-y", str(out)]
    result = subprocess.run(cmd, capture_output=True, timeout=3600)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")[-200:]
        raise RuntimeError(f"ffmpeg failed for track {num}: {err}")
