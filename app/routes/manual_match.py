import os
import re
from pathlib import Path

from flask import Blueprint, Response, abort, render_template, request, stream_with_context

from app import staging as _staging
from app.importer import stream_import
from app.lock import acquire_lock, release_lock
from app.musicbrainz import get_release_by_id, search_releases
from app.pipeline.matcher import normalise_title as _normalise
from app.pipeline.probe import probe_cue
from app.pipeline.splitter import split_cue_rip
from app.types import TrackDetail, TrackRow

bp = Blueprint("manual_match", __name__)


def _local_tracks(stage_path: str) -> list[str]:
    audio_exts = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".wv", ".ape", ".dsf", ".dff"}
    try:
        return [f for f in sorted(os.listdir(stage_path)) if os.path.splitext(f)[1].lower() in audio_exts]
    except OSError:
        return []


def _cue_tracks(stage_path: str) -> list[str]:
    """Return track titles from a .cue file in the parent directory of stage_path."""
    parent = os.path.dirname(stage_path)
    try:
        cue_files = sorted(f for f in os.listdir(parent) if f.lower().endswith(".cue"))
    except OSError:
        return []
    if not cue_files:
        return []
    tracks: list[str] = []
    in_track = False
    try:
        with open(os.path.join(parent, cue_files[0]), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if re.match(r"TRACK\s+\d+\s+AUDIO", line, re.IGNORECASE):
                    in_track = True
                elif in_track and re.match(r'TITLE\s+"', line, re.IGNORECASE):
                    m = re.match(r'TITLE\s+"(.+)"', line, re.IGNORECASE)
                    if m:
                        tracks.append(m.group(1))
                    in_track = False
    except OSError:
        return []
    return tracks


def _stage_info(stage_path: str) -> tuple[list[str], bool, bool]:
    """Return (display_tracks, using_cue, is_single_flac) from a single directory read."""
    files = _local_tracks(stage_path)
    single_flac = len(files) == 1 and files[0].lower().endswith(".flac")
    if single_flac:
        cue = _cue_tracks(stage_path)
        if cue:
            return cue, True, True
    return files, False, single_flac


def _compare_tracks(local_files: list[str], mb_tracks: list[TrackDetail]) -> list[TrackRow]:
    local_norm = [(_normalise(os.path.splitext(f)[0]), f) for f in local_files]
    mb_norm = [(_normalise(t["title"]), t) for t in mb_tracks]

    rows: list[TrackRow] = []
    used_local: set[int] = set()

    for mi, (mn, mt) in enumerate(mb_norm):
        best_li: int | None = None
        for li, (ln, _) in enumerate(local_norm):
            if li not in used_local and ln == mn:
                best_li = li
                break
        if best_li is not None:
            used_local.add(best_li)
            rows.append(TrackRow(local=local_norm[best_li][1], mb=mt["title"], status="match", mb_pos=mt["position"]))
        else:
            fuzzy: int | None = next(
                (li for li, (ln, _) in enumerate(local_norm) if li not in used_local and (mn in ln or ln in mn)),
                None,
            )
            if fuzzy is not None:
                used_local.add(fuzzy)
                rows.append(TrackRow(local=local_norm[fuzzy][1], mb=mt["title"], status="diff", mb_pos=mt["position"]))
            else:
                rows.append(TrackRow(local=None, mb=mt["title"], status="missing", mb_pos=mt["position"]))

    for li, (_, lf) in enumerate(local_norm):
        if li not in used_local:
            rows.append(TrackRow(local=lf, mb=None, status="extra", mb_pos=None))

    rows.sort(key=lambda r: (r["mb_pos"] or 999, r["local"] or ""))
    return rows


@bp.route("/manual-match")
def index():
    stage_path = request.args.get("stage_path", "")
    _, _, single_flac = _stage_info(stage_path)
    return render_template(
        "manual_match.html",
        stage_path=stage_path,
        query="",
        artist="",
        candidates=[],
        searched=False,
        apply_id_release=None,
        track_rows=[],
        local_tracks=[],
        using_cue=False,
        single_flac=single_flac,
    )


@bp.route("/manual-match/search", methods=["POST"])
def search():
    stage_path = request.form.get("stage_path", "")
    query = request.form.get("query", "").strip()
    artist = request.form.get("artist", "").strip()
    has_input = bool(query or artist)
    candidates = search_releases(query, artist=artist, title=query) if has_input else []
    local_tracks, using_cue, single_flac = _stage_info(stage_path)
    for c in candidates:
        mb_tracks = [TrackDetail(position=i + 1, title=t) for i, t in enumerate(c["tracks"])]
        if mb_tracks and local_tracks:
            rows = _compare_tracks(local_tracks, mb_tracks)
            matched = sum(1 for r in rows if r["status"] == "match")
            total = max(len(mb_tracks), len(local_tracks))
            c["score"] = int(matched / total * 100) if total > 0 else 0
            c["score_label"] = "track match"
            c["track_rows"] = rows
        elif local_tracks and c["track_count"] > 0:
            # MB search results omit track listings — score by track count similarity
            local_count = len(local_tracks)
            mb_count = c["track_count"]
            c["score"] = int(min(local_count, mb_count) / max(local_count, mb_count) * 100)
            c["score_label"] = "track count"
            c["track_rows"] = []
        else:
            c["score_label"] = "relevance"
            c["track_rows"] = []
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return render_template(
        "manual_match.html",
        stage_path=stage_path,
        query=query,
        artist=artist,
        candidates=candidates,
        searched=True,
        apply_id_release=None,
        track_rows=[],
        local_tracks=local_tracks,
        using_cue=using_cue,
        single_flac=single_flac,
    )


@bp.route("/manual-match/apply-by-id", methods=["POST"])
def apply_by_id():
    stage_path = request.form.get("stage_path", "")
    mb_uuid = request.form.get("mb_uuid", "").strip()
    release = get_release_by_id(mb_uuid) if mb_uuid else None
    local_tracks, using_cue, single_flac = _stage_info(stage_path)
    track_rows = _compare_tracks(local_tracks, release["tracks"]) if release else []
    return render_template(
        "manual_match.html",
        stage_path=stage_path,
        query="",
        candidates=[],
        searched=False,
        apply_id_release=release,
        track_rows=track_rows,
        local_tracks=local_tracks,
        using_cue=using_cue,
        single_flac=single_flac,
    )


@bp.route("/manual-match/stream")
def stream():
    stage_path = request.args.get("stage_path", "")
    mb_uuid = request.args.get("mb_uuid") or None
    use_as_is = request.args.get("use_as_is") == "1"

    if not acquire_lock(stage_path):
        abort(409)

    def generate():
        try:
            yield from stream_import(stage_path, mb_uuid=mb_uuid, use_as_is=use_as_is)
        finally:
            release_lock()

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/manual-match/split-by-mb")
def split_by_mb():
    """Split a CUE rip (single FLAC + .cue) into individual tracks using the CUE timings.

    stage_path is the original download directory containing the CUE + FLAC source files.
    mb_uuid is required (ensures the button is only invoked alongside a known MB candidate)
    but is not used for splitting — CUE timings are used directly. The caller should
    proceed to /manual-match/stream with the same mb_uuid after split completes.
    """
    stage_path = request.args.get("stage_path", "")
    mb_uuid = request.args.get("mb_uuid", "").strip()

    if not mb_uuid:
        abort(400)
    if not acquire_lock(stage_path):
        abort(409)

    def generate():
        try:
            source = Path(stage_path)                    # download dir: contains CUE + FLAC
            stage = _staging.create_stage(stage_path)   # staging dir for split output
            probe = probe_cue(source)                    # look in source, not source.parent
            if not probe.source_file:
                yield "data: [ERROR] No audio source found in download directory\n\n"
                yield "data: [DONE]\n\n"
                return

            yield f"data: Splitting {probe.track_count} tracks...\n\n"
            try:
                split_cue_rip(source, stage, probe)
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"
                yield "data: [DONE]\n\n"
                return
            yield f"data: Done — {probe.track_count} tracks written to stage.\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] Unexpected error: {e}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            release_lock()

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
