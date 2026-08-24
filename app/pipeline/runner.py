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
    RELAXED_DISC_PATTERN,
    disc_is_image_cue,
    find_import_jobs,
    looks_like_multi_disc_cue_rip,
    looks_like_multi_disc_regular,
)
from app.pipeline.importer import ImportResult, run_beet_command, run_beet_import
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


def _beets_remove_path(path: Path) -> None:
    """Remove all beets DB entries for files under path, without deleting the files.

    Called before re-importing library files during a rematch so that beet does
    not treat the existing entries as duplicates and skip them (duplicate_action:
    skip in config.yaml). The files themselves stay on disk; beet re-creates the
    DB entries from scratch with the new MB metadata.
    """
    result = run_beet_command(["beet", "remove", "-f", f"path:{path}"], timeout=30)
    if result.returncode != 0:
        log.warning("beet remove pre-step failed for %s: %s", path, result.stderr or result.stdout)
    else:
        log.debug("beet remove pre-step: cleared DB entries for %s", path)


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

    # Rematch (move=True): files are already in the library. Remove their DB
    # entries first so beet does not see them as duplicates and skip.
    if move:
        _beets_remove_path(root)

    ctx = ImportContext(
        source_path=path,
        noincremental=noincremental,
        mb_id_override=mb_id_override,
        move=move,
    )

    statuses: list[str] = []

    if mb_id_override and looks_like_multi_disc_cue_rip(root):
        statuses.append(_process_multi_disc_cue_override(root, ctx))
    elif mb_id_override and looks_like_multi_disc_regular(root):
        statuses.append(_process_multi_disc_regular_override(root, ctx))
    else:
        jobs = find_import_jobs(root)
        if not jobs:
            log.warning("No importable albums found in %s", path)
            _log_beet_output("Skipped (no audio found)\n")
            log_failed(path, "skipped")
            return

        for job in jobs:
            if isinstance(job, CueRipJob):
                statuses.append(_process_cue_rip(job, ctx))
            elif isinstance(job, MultiCueRipJob):
                statuses.append(_process_multi_cue_rip(job, ctx))
            elif isinstance(job, MultiFileCueJob):
                statuses.append(_process_multi_file_cue(job, ctx))
            elif isinstance(job, RegularJob):
                statuses.append(_process_regular(job, ctx))
            elif isinstance(job, MultiDiscJob):
                statuses.append(_process_multi_disc(job, ctx))

    # Rematch safety net: the DB entries were removed up front. If nothing was
    # imported, restore the original entries so the album doesn't vanish from
    # the library.
    if move and not any(s in ("imported", "duplicate") for s in statuses):
        _restore_after_failed_rematch(root)


def _process_cue_rip(job: CueRipJob, ctx: ImportContext) -> str:
    stage_dir = staging.create_stage(str(job.path))
    probe = probe_cue(job.path)

    if not list(stage_dir.glob("*.flac")):
        try:
            split_cue_rip(job.path, stage_dir, probe)
        except Exception as e:
            log.error("Split failed for %s: %s", job.path, e)
            log_failed(str(job.path), "skipped")
            staging.delete_stage(str(job.path))
            return "skipped"

    mb_id = _resolve_mb_id(ctx, probe)
    result = run_beet_import(str(stage_dir), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_cue_rip(job: MultiCueRipJob, ctx: ImportContext) -> str:
    cue_files = sorted(
        f for f in job.path.iterdir()
        if f.suffix.lower() == ".cue" and "isrc" not in f.name.lower()
    )
    if not cue_files:
        log_failed(str(job.path), "skipped")
        return "skipped"

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
                return "skipped"

    combined = _merge_probes(first_probe, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_file_cue(job: MultiFileCueJob, ctx: ImportContext) -> str:
    sections = probe_multi_file_cue(job.path)
    if not sections:
        log.warning("No sections found in multi-file CUE for %s", job.path)
        log_failed(str(job.path), "skipped")
        return "skipped"

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
            return "skipped"
        all_titles.extend(section.track_titles)

    combined = _merge_probes(first, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_dir), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, str(job.path))


def _process_regular(job: RegularJob, ctx: ImportContext) -> str:
    probe = probe_flac(job.path)

    # If FLAC tags are entirely absent, fall back to any companion CUE for artist/album/year.
    # Keeps the FLAC-derived track count and filename-based track titles so MB matching still
    # works — the CUE just provides the identity metadata the empty tags can't supply.
    if not probe.artist and not probe.album:
        cue_probe = probe_cue(job.path)
        if cue_probe.artist or cue_probe.album:
            log.debug(
                "No FLAC tags in %s — using CUE metadata (artist=%r, album=%r)",
                job.path, cue_probe.artist, cue_probe.album,
            )
            probe = ProbeResult(
                artist=cue_probe.artist,
                album=cue_probe.album,
                track_count=probe.track_count,
                track_titles=probe.track_titles,
            )

    mb_id = _resolve_mb_id(ctx, probe)

    # Nothing identifies this album: no tags, no usable CUE, and no MB match to
    # fall back on. Importing anyway means --noautotag over untagged files, which
    # files a blank album and exits 0 — so it never surfaces for review. Send it
    # to the Failed Imports tab instead and let the user pick a release.
    if mb_id is None and not probe.artist and not probe.album:
        log.warning("No usable metadata for %s — routing to failed imports", job.path)
        _log_beet_output("Skipped (no tags, no CUE metadata, no MusicBrainz match)\n")
        log_failed(str(job.path), "blank-metadata")
        return "blank-metadata"

    result = run_beet_import(str(job.path), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, str(job.path))


def _process_multi_disc(job: MultiDiscJob, ctx: ImportContext) -> str:
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
        return _handle_result(result, ctx.source_path, str(job.path))

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
                return "skipped"

    combined = _merge_probes(first_probe, all_titles)
    mb_id = _resolve_mb_id(ctx, combined)
    result = run_beet_import(str(stage_root), mb_id=mb_id, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, str(job.path))


def _handle_result(result: ImportResult, source_path: str, album_path: str) -> str:
    _log_beet_output(result.output)
    if result.status in ("imported", "duplicate"):
        staging.delete_stage(album_path)
    elif result.status in ("nomatch", "timeout"):
        kind = "nomatch" if result.status == "nomatch" else "skipped"
        log_failed(album_path, kind)
    return result.status


def _log_processing(path: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(config.ON_COMPLETE_LOG, f"{ts} import-watcher: processing {path}\n")


def _log_beet_output(output: str) -> None:
    if output:
        _append(config.ON_COMPLETE_LOG, output if output.endswith("\n") else output + "\n")


def log_failed(path: str, kind: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(config.IMPORT_FAILED_LOG, f"{ts} | {kind} | {path}\n")


def _process_multi_disc_regular_override(
    root: Path,
    ctx: ImportContext,
) -> str:
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
        statuses = [
            _process_regular(job, ctx) for job in jobs if isinstance(job, RegularJob)
        ]
        if "imported" in statuses:
            return "imported"
        return statuses[0] if statuses else "skipped"

    audio_subdirs = sorted(
        d for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and any(f.is_file() and f.suffix.lower() in AUDIO_EXTS for f in d.iterdir())
    )
    if len(audio_subdirs) < 2:
        log_failed(ctx.source_path, "skipped")
        return "skipped"

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
    return _handle_result(result, ctx.source_path, ctx.source_path)


def _process_multi_disc_cue_override(
    root: Path,
    ctx: ImportContext,
) -> str:
    """Split each disc-image CUE rip under *root* into a shared staging tree and import together.

    Used when the user has supplied a specific MusicBrainz release ID for a multi-disc
    compilation whose subdirectory names don't match the strict DISC_PATTERN (e.g.
    "CD01 - Somethin' Else" instead of plain "CD1").
    """
    disc_dirs = sorted(
        d for d in root.iterdir()
        if d.is_dir() and RELAXED_DISC_PATTERN.match(d.name)
    )
    if not disc_dirs:
        log_failed(ctx.source_path, "skipped")
        return "skipped"

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
                return "skipped"

    result = run_beet_import(str(stage_root), mb_id=ctx.mb_id_override, noincremental=ctx.noincremental, move=ctx.move)
    return _handle_result(result, ctx.source_path, ctx.source_path)


def _restore_after_failed_rematch(root: Path) -> None:
    """Re-import library files as-is after a failed rematch.

    run() removes the album's DB entries before a rematch import (otherwise
    duplicate_action: skip blocks it). If that import then fails, the files
    are still on disk but invisible to the library — re-import them with
    their existing tags (--noautotag) to restore the entries.
    """
    log.warning("Rematch failed for %s — restoring original library entries", root)
    result = run_beet_import(str(root), mb_id=None, noincremental=True)
    _log_beet_output(result.output)
    if result.status not in ("imported", "duplicate"):
        log_failed(str(root), "rematch-orphaned")


def _append(filepath: str, text: str) -> None:
    with open(filepath, "a") as f:
        f.write(text)
