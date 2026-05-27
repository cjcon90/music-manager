import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app import config, staging
from app.pipeline import AUDIO_EXTS, DISC_PATTERN
from app.pipeline.detector import (
    CueRipJob,
    MultiCueRipJob,
    MultiDiscJob,
    MultiFileCueJob,
    RegularJob,
    _RELAXED_DISC_PATTERN,
    disc_is_image_cue,
    find_import_jobs,
    looks_like_multi_disc_cue_rip,
    looks_like_multi_disc_regular,
)
from app.pipeline.importer import ImportResult, run_beet_import
from app.pipeline.matcher import find_best_release
from app.pipeline.probe import ProbeResult, probe_cue, probe_cue_file, probe_flac, probe_multi_file_cue
from app.pipeline.splitter import split_cue_rip

log = logging.getLogger(__name__)


@dataclass
class ImportContext:
    """Run-time options for a single import job.

    source_path: the original queue path used only for failure logging — it may
    be a parent directory of the album being imported (when a queue entry covers
    multiple albums).
    """
    source_path: str
    noincremental: bool
    mb_id_override: str | None
    move: bool


def _merge_probes(first: ProbeResult | None, all_titles: list[str]) -> ProbeResult:
    """Combine per-disc ProbeResults into one for MB matching.

    Used by multi-disc and multi-CUE handlers where each disc is probed
    separately but a single combined track list is needed for the matcher.
    first may be None if no discs were found; in that case metadata is empty.
    """
    return ProbeResult(
        artist=first.artist if first else "",
        album=first.album if first else "",
        year=first.year if first else "",
        track_count=len(all_titles),
        track_titles=all_titles,
    )


def _resolve_mb_id(ctx: ImportContext, probe: ProbeResult) -> str | None:
    """Return the MB release ID to use for this import.

    Uses ctx.mb_id_override when set (user-chosen release, skips matcher).
    Falls back to searching MusicBrainz using probe metadata.
    """
    return ctx.mb_id_override if ctx.mb_id_override else find_best_release(probe)


def run(
    path: str,
    noincremental: bool = True,
    mb_id_override: str | None = None,
    move: bool = False,
) -> None:
    """Run the full import pipeline for a path.

    Entry point called by the watcher for every .path file. Detects the album
    type, handles any pre-detection overrides for multi-disc releases, then
    dispatches to the appropriate handler.
    """
    _log_processing(path)
    root = Path(path)
    ctx = ImportContext(
        source_path=path,
        noincremental=noincremental,
        mb_id_override=mb_id_override,
        move=move,
    )

    if mb_id_override and looks_like_multi_disc_cue_rip(root):
        _process_multi_disc_cue_override(root, ctx)
        return

    if mb_id_override and looks_like_multi_disc_regular(root):
        _process_multi_disc_regular_override(root, ctx)
        return

    jobs = find_import_jobs(root)
    if not jobs:
        log.warning("No importable albums found in %s", path)
        _log_beet_output("Skipped (no audio found)\n")
        _log_failed(path, "skipped")
        return

    for job in jobs:
        if isinstance(job, CueRipJob):
            _process_cue_rip(job, ctx)
        elif isinstance(job, MultiCueRipJob):
            _process_multi_cue_rip(job, ctx)
        elif isinstance(job, MultiFileCueJob):
            _process_multi_file_cue(job, ctx)
        elif isinstance(job, RegularJob):
            _process_regular(job, ctx)
        elif isinstance(job, MultiDiscJob):
            _process_multi_disc(job, ctx)


def _process_cue_rip(job: CueRipJob, ctx: ImportContext) -> None:
    stage_dir = staging.create_stage(str(job.path))
    probe = probe_cue(job.path)

    if not list(stage_dir.glob("*.flac")):
        try:
            split_cue_rip(job.path, stage_dir, probe)
        except Exception as e:
            log.error("Split failed for %s: %s", job.path, e)
            log_failed(str(job.path), "skipped")
            staging.delete_stage(str(job.path))
            return

    mb_id = _resolve_mb_id(ctx, probe)
    result = run_beet_import(str(stage_dir), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_cue_rip(job: MultiCueRipJob, ctx: ImportContext) -> None:
    cue_files = sorted(
        f for f in job.path.iterdir()
        if f.suffix.lower() == ".cue" and "isrc" not in f.name.lower()
    )
    if not cue_files:
        log_failed(str(job.path), "skipped")
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
                log_failed(str(job.path), "skipped")
                staging.delete_stage(str(job.path))
                return

    combined = _merge_probes(first_probe, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_file_cue(job: MultiFileCueJob, ctx: ImportContext) -> None:
    sections = probe_multi_file_cue(job.path)
    if not sections:
        log.warning("No sections found in multi-file CUE for %s", job.path)
        log_failed(str(job.path), "skipped")
        return

    stage_dir = staging.create_stage(str(job.path))
    all_titles: list[str] = []
    first: ProbeResult = sections[0]

    for section in sections:
        first_num = section.track_numbers[0] if section.track_numbers else 1
        if list(stage_dir.glob(f"{first_num:02d} - *.flac")):
            all_titles.extend(section.track_titles)
            continue
        try:
            split_cue_rip(job.path, stage_dir, section)
        except Exception as e:
            log.error("Split failed for %s (%s): %s", job.path, section.source_file, e)
            log_failed(str(job.path), "skipped")
            staging.delete_stage(str(job.path))
            return
        all_titles.extend(section.track_titles)

    combined = _merge_probes(first, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_dir), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, str(job.path))


def _process_regular(job: RegularJob, ctx: ImportContext) -> None:
    probe = probe_flac(job.path)
    mb_id = _resolve_mb_id(ctx, probe)
    result = run_beet_import(str(job.path), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_disc(job: MultiDiscJob, ctx: ImportContext) -> None:
    disc_dirs = sorted(
        d for d in job.path.iterdir()
        if d.is_dir() and DISC_PATTERN.match(d.name)
    )
    has_cue = any(disc_is_image_cue(d) for d in disc_dirs)

    if not has_cue:
        all_titles: list[str] = []
        first_probe: ProbeResult | None = None
        for d in disc_dirs:
            p = probe_flac(d)
            if first_probe is None:
                first_probe = p
            all_titles.extend(p.track_titles)
        combined = _merge_probes(first_probe, all_titles)
        mb_id = _resolve_mb_id(ctx, combined)
        result = run_beet_import(str(job.path), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
        _handle_result(result, ctx.source_path, str(job.path))
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
                log_failed(str(job.path), "skipped")
                staging.delete_stage(str(job.path))
                return

    combined = _merge_probes(first_probe, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, str(job.path))


def _handle_result(result: ImportResult, source_path: str, album_path: str) -> None:
    _log_beet_output(result.output)
    if result.status in ("imported", "duplicate"):
        staging.delete_stage(album_path)
    elif result.status in ("nomatch", "timeout"):
        kind = "nomatch" if result.status == "nomatch" else "skipped"
        _log_failed(album_path, kind)


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


def _process_multi_disc_regular_override(
    root: Path,
    ctx: ImportContext,
) -> None:
    """Stage multiple audio subdirs as CD 01/ CD 02/ etc. and import as one release.

    Uses symlinks rather than copies to avoid duplicating large FLAC files across
    ZFS datasets.  The staging directory is cleaned up after a successful import.

    Note: move=True is not supported here — this function is only reachable for
    fresh imports (never library rematches), so move is always False in practice.
    The guard below makes that invariant explicit.
    """
    if ctx.move:
        log.warning(
            "_process_multi_disc_regular_override called with move=True for %s — "
            "falling back to normal pipeline",
            root,
        )
        jobs = find_import_jobs(root)
        for job in jobs:
            if isinstance(job, RegularJob):
                _process_regular(job, ctx)
        return

    audio_subdirs = sorted(
        d for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and any(f.is_file() and f.suffix.lower() in AUDIO_EXTS for f in d.iterdir())
    )
    if len(audio_subdirs) < 2:
        log_failed(ctx.source_path, "skipped")
        return

    stage_root = staging.create_stage(ctx.source_path)

    for i, subdir in enumerate(audio_subdirs, 1):
        stage_disc = stage_root / f"CD {i:02d}"
        stage_disc.mkdir(exist_ok=True)
        if not any(stage_disc.iterdir()):
            for audio_file in sorted(
                f for f in subdir.iterdir()
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS
            ):
                link = stage_disc / audio_file.name
                if not link.exists():
                    link.symlink_to(audio_file.resolve())

    result = run_beet_import(
        str(stage_root),
        mb_id=ctx.mb_id_override,
        noincremental=ctx.noincremental,
        move=ctx.move,
    )
    _handle_result(result, ctx.source_path, ctx.source_path)


def _process_multi_disc_cue_override(
    root: Path,
    ctx: ImportContext,
) -> None:
    """Split each disc-image CUE rip under *root* into a shared staging tree and import together.

    Used when the user has supplied a specific MusicBrainz release ID for a multi-disc
    compilation whose subdirectory names don't match the strict DISC_PATTERN (e.g.
    "CD01 - Somethin' Else" instead of plain "CD1").
    """
    disc_dirs = sorted(
        d for d in root.iterdir()
        if d.is_dir() and _RELAXED_DISC_PATTERN.match(d.name)
    )
    if not disc_dirs:
        log_failed(ctx.source_path, "skipped")
        return

    stage_root = staging.create_stage(ctx.source_path)

    for i, disc_dir in enumerate(disc_dirs, 1):
        disc_probe = probe_cue(disc_dir)
        stage_disc = stage_root / f"CD {i:02d}"
        if not (stage_disc.exists() and list(stage_disc.glob("*.flac"))):
            try:
                split_cue_rip(disc_dir, stage_disc, disc_probe)
            except Exception as e:
                log.error("Split failed for %s: %s", disc_dir, e)
                log_failed(ctx.source_path, "skipped")
                staging.delete_stage(ctx.source_path)
                return

    result = run_beet_import(str(stage_root), mb_id=ctx.mb_id_override, noincremental=ctx.noincremental, move=ctx.move)
    _handle_result(result, ctx.source_path, ctx.source_path)


def _append(filepath: str, text: str) -> None:
    with open(filepath, "a") as f:
        f.write(text)
