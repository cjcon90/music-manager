import hashlib
import os
import re
import time
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, render_template, request, stream_with_context

from app import staging as _staging
from app.beets_api import get_album_by_id
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


def _parse_album_id(raw: str) -> int | None:
    return int(raw) if raw.isdigit() else None


@bp.route("/manual-match")
def index():
    stage_path = request.args.get("stage_path", "")
    album_id = _parse_album_id(request.args.get("album_id", ""))
    from_library = album_id is not None

    prefill_artist = ""
    prefill_query = ""

    # Library rematch: derive stage_path from DB and pre-fill search fields
    if from_library and not stage_path:
        album = get_album_by_id(album_id)
        if album and album["path"]:
            stage_path = str(Path(album["path"]).parent)
            prefill_artist = album["artist"]
            prefill_query = album["album"]

    _, _, single_flac = _stage_info(stage_path)
    return render_template(
        "manual_match.html",
        stage_path=stage_path,
        album_id=album_id,
        from_library=from_library,
        query=prefill_query,
        artist=prefill_artist,
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
    album_id = _parse_album_id(request.form.get("album_id", ""))
    from_library = album_id is not None
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
        album_id=album_id,
        from_library=from_library,
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
    album_id = _parse_album_id(request.form.get("album_id", ""))
    from_library = album_id is not None
    mb_uuid = request.form.get("mb_uuid", "").strip()
    release = get_release_by_id(mb_uuid) if mb_uuid else None
    local_tracks, using_cue, single_flac = _stage_info(stage_path)
    track_rows = _compare_tracks(local_tracks, release["tracks"]) if release else []
    return render_template(
        "manual_match.html",
        stage_path=stage_path,
        album_id=album_id,
        from_library=from_library,
        query="",
        candidates=[],
        searched=False,
        apply_id_release=release,
        track_rows=track_rows,
        local_tracks=local_tracks,
        using_cue=using_cue,
        single_flac=single_flac,
    )


@bp.route("/manual-match/queue-apply", methods=["POST"])
def queue_apply():
    """Queue a manual-match import job — returns immediately, watcher applies it in the background.

    This mirrors /album/<id>/queue-rematch but is used for failed imports where we have a
    stage_path (the original failed job directory) rather than a library album_id.
    """
    from app import config
    from app.routes.failed import dismiss_failed_entry as _dismiss

    stage_path = request.form.get("stage_path", "").strip()
    mb_uuid = request.form.get("mb_uuid", "").strip()

    if not stage_path:
        return jsonify({"ok": False, "error": "stage_path required"}), 400
    if not mb_uuid or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        mb_uuid, re.IGNORECASE,
    ):
        return jsonify({"ok": False, "error": "invalid mb_uuid"}), 400

    queue_dir = Path(config.IMPORT_QUEUE_DIR)
    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o777)

    tag = hashlib.sha256(f"manual-{stage_path}-{mb_uuid}-{time.time()}".encode()).hexdigest()[:8]
    path_file = queue_dir / f"manual-{tag}.path"
    path_file.write_text(f"{stage_path}\n--noincremental\n--search-id={mb_uuid}\n")

    # Optimistically dismiss the failed-imports entry so the UI stays clean
    _dismiss(stage_path)

    return jsonify({"ok": True})


@bp.route("/manual-match/split-by-mb")
def split_by_mb():
    """Split a CUE rip (single FLAC + .cue) into individual tracks using the CUE timings.

    stage_path is the original download directory containing the CUE + FLAC source files.
    mb_uuid is required (ensures the button is only invoked alongside a known MB candidate)
    but is not used for splitting — CUE timings are used directly.
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
