import logging
import time
from pathlib import Path

from app import config, staging
from app.pipeline import AUDIO_EXTS, DISC_PATTERN
from app.pipeline.detector import CueRipJob, MultiCueRipJob, MultiDiscJob, RegularJob, find_import_jobs
from app.pipeline.importer import ImportResult, run_beet_import
from app.pipeline.matcher import find_best_release
from app.pipeline.probe import ProbeResult, probe_cue, probe_cue_file, probe_flac
from app.pipeline.splitter import split_cue_rip

log = logging.getLogger(__name__)


def run(
    path: str,
    noincremental: bool = True,
    mb_id_override: str | None = None,
    move: bool = False,
) -> None:
    """Run the full import pipeline for a path.

    mb_id_override: skip the matcher and apply this specific MusicBrainz release ID.
                    Used for library rematches where the user has already chosen the release.
    move:           pass --move to beet so files are relocated rather than copied.
                    Used for library rematches to avoid orphaned files when the path changes.
    """
    _log_processing(path)
    root = Path(path)

    jobs = find_import_jobs(root)
    if not jobs:
        log.warning("No importable albums found in %s", path)
        _log_beet_output("Skipped (no audio found)\n")
        _log_failed(path, "skipped")
        return

    for job in jobs:
        if isinstance(job, CueRipJob):
            _process_cue_rip(job, path, noincremental, mb_id_override=mb_id_override, move=move)
        elif isinstance(job, MultiCueRipJob):
            _process_multi_cue_rip(job, path, noincremental, mb_id_override=mb_id_override, move=move)
        elif isinstance(job, RegularJob):
            _process_regular(job, path, noincremental, mb_id_override=mb_id_override, move=move)
        elif isinstance(job, MultiDiscJob):
            _process_multi_disc(job, path, noincremental, mb_id_override=mb_id_override, move=move)


def _process_cue_rip(job: CueRipJob, source_path: str, noincremental: bool, mb_id_override: str | None = None, move: bool = False) -> None:
    stage_dir = staging.create_stage(str(job.path))
    probe = probe_cue(job.path)

    if not list(stage_dir.glob("*.flac")):
        try:
            split_cue_rip(job.path, stage_dir, probe)
        except Exception as e:
            log.error("Split failed for %s: %s", job.path, e)
            _log_failed(source_path, "skipped")
            staging.delete_stage(str(job.path))
            return

    mb_id = mb_id_override if mb_id_override else find_best_release(probe)
    result = run_beet_import(str(stage_dir), mb_id=mb_id, noincremental=noincremental, move=move)
    _handle_result(result, source_path, str(job.path))


def _process_multi_cue_rip(job: MultiCueRipJob, source_path: str, noincremental: bool, mb_id_override: str | None = None, move: bool = False) -> None:
    """Handle a directory with N paired FLAC+CUE files (e.g. a 2-disc album as whole-disc rips)."""
    cue_files = sorted(
        f for f in job.path.iterdir()
        if f.suffix.lower() == ".cue" and "isrc" not in f.name.lower()
    )
    if not cue_files:
        _log_failed(source_path, "skipped")
        return

    stage_root = staging.create_stage(str(job.path))
    all_titles: list[str] = []
    first_probe: ProbeResult | None = None

    for i, cue_file in enumerate(cue_files, 1):
        disc_probe = probe_cue_file(job.path, cue_file)
        if first_probe is None:
            first_probe = disc_probe
        all_titles.extend(disc_probe.track_titles)
        disc_dir = stage_root / f"CD{i}"
        if not (disc_dir.exists() and list(disc_dir.glob("*.flac"))):
            try:
                split_cue_rip(job.path, disc_dir, disc_probe)
            except Exception as e:
                log.error("Split failed for %s disc %d: %s", job.path, i, e)
                _log_failed(source_path, "skipped")
                staging.delete_stage(str(job.path))
                return

    combined = ProbeResult(
        artist=first_probe.artist if first_probe else "",
        album=first_probe.album if first_probe else "",
        year=first_probe.year if first_probe else "",
        track_count=len(all_titles),
        track_titles=all_titles,
    )
    mb_id = mb_id_override if mb_id_override else find_best_release(combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=noincremental, move=move)
    _handle_result(result, source_path, str(job.path))


def _process_regular(job: RegularJob, source_path: str, noincremental: bool, mb_id_override: str | None = None, move: bool = False) -> None:
    probe = probe_flac(job.path)
    mb_id = mb_id_override if mb_id_override else find_best_release(probe)
    result = run_beet_import(str(job.path), mb_id=mb_id, noincremental=noincremental, move=move)
    _handle_result(result, source_path, str(job.path))


def _disc_is_image_cue(d: Path) -> bool:
    """Return True only if this disc dir is an unsplit disc image: single audio file + CUE.

    Pre-split albums sometimes include a leftover .cue file alongside the individual tracks;
    those should NOT be treated as disc images requiring splitting.
    """
    audio = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
    cue = list(d.glob("*.cue")) + list(d.glob("*.CUE"))
    return len(audio) == 1 and len(cue) >= 1


def _process_multi_disc(job: MultiDiscJob, source_path: str, noincremental: bool, mb_id_override: str | None = None, move: bool = False) -> None:
    disc_dirs = sorted(
        d for d in job.path.iterdir()
        if d.is_dir() and DISC_PATTERN.match(d.name)
    )
    has_cue = any(_disc_is_image_cue(d) for d in disc_dirs)

    if not has_cue:
        all_titles: list[str] = []
        first_probe: ProbeResult | None = None
        for d in disc_dirs:
            p = probe_flac(d)
            if first_probe is None:
                first_probe = p
            all_titles.extend(p.track_titles)
        combined = ProbeResult(
            artist=first_probe.artist if first_probe else "",
            album=first_probe.album if first_probe else "",
            year=first_probe.year if first_probe else "",
            track_count=len(all_titles),
            track_titles=all_titles,
        )
        mb_id = mb_id_override if mb_id_override else find_best_release(combined)
        result = run_beet_import(str(job.path), mb_id=mb_id, noincremental=noincremental, move=move)
        _handle_result(result, source_path, str(job.path))
        return

    stage_root = staging.create_stage(str(job.path))
    all_titles = []
    first_probe = None

    for disc_dir in disc_dirs:
        disc_probe = probe_cue(disc_dir)
        if first_probe is None:
            first_probe = disc_probe
        all_titles.extend(disc_probe.track_titles)
        stage_disc = stage_root / disc_dir.name
        if not (stage_disc.exists() and list(stage_disc.glob("*.flac"))):
            try:
                split_cue_rip(disc_dir, stage_disc, disc_probe)
            except Exception as e:
                log.error("Split failed for %s: %s", disc_dir, e)
                _log_failed(source_path, "skipped")
                staging.delete_stage(str(job.path))
                return

    combined = ProbeResult(
        artist=first_probe.artist if first_probe else "",
        album=first_probe.album if first_probe else "",
        year=first_probe.year if first_probe else "",
        track_count=len(all_titles),
        track_titles=all_titles,
    )
    mb_id = mb_id_override if mb_id_override else find_best_release(combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=noincremental, move=move)
    _handle_result(result, source_path, str(job.path))


def _handle_result(result: ImportResult, source_path: str, album_path: str) -> None:
    _log_beet_output(result.output)
    if result.status in ("imported", "duplicate"):
        staging.delete_stage(album_path)
    elif result.status in ("nomatch", "timeout"):
        kind = "nomatch" if result.status == "nomatch" else "skipped"
        _log_failed(source_path, kind)


def _log_processing(path: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(config.ON_COMPLETE_LOG, f"{ts} import-watcher: processing {path}\n")


def _log_beet_output(output: str) -> None:
    if output:
        _append(config.ON_COMPLETE_LOG, output if output.endswith("\n") else output + "\n")


def log_failed(path: str, kind: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(config.IMPORT_FAILED_LOG, f"{ts} | {kind} | {path}\n")


def _log_failed(path: str, kind: str) -> None:
    log_failed(path, kind)


def _append(filepath: str, text: str) -> None:
    with open(filepath, "a") as f:
        f.write(text)
