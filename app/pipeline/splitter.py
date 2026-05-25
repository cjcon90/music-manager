import re
import subprocess
from pathlib import Path

from app.pipeline.probe import ProbeResult, probe_cue


def split_cue_rip(source_dir: Path, stage_dir: Path, probe: ProbeResult | None = None) -> None:
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
        num = i + 1
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
