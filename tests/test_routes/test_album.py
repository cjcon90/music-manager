from unittest.mock import MagicMock, patch

_BASE_ALBUM = {
    "id": 1,
    "album": "Ziggy Stardust",
    "artist": "David Bowie",
    "year": 1972,
    "tracks": 11,
    "path": "/media/music/David Bowie/Ziggy Stardust (1972)/01.flac",
    "artpath": None,
    "mb_albumid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
    "format": "FLAC",
}


@patch("app.routes.album.get_album_by_id", return_value={**_BASE_ALBUM, "artpath": None})
def test_art_returns_svg_when_no_artpath(mock_get, client):
    resp = client.get("/album/1/art")
    assert resp.status_code == 200
    assert resp.content_type == "image/svg+xml"


@patch("app.routes.album.get_album_by_id", return_value=None)
def test_art_returns_svg_when_album_not_found(mock_get, client):
    resp = client.get("/album/999/art")
    assert resp.status_code == 200
    assert resp.content_type == "image/svg+xml"


@patch("app.routes.album.get_album_by_id")
def test_art_returns_svg_when_file_missing_from_disk(mock_get, client, tmp_path):
    missing = str(tmp_path / "nonexistent.jpg")
    mock_get.return_value = {**_BASE_ALBUM, "artpath": missing}
    resp = client.get("/album/1/art")
    assert resp.status_code == 200
    assert resp.content_type == "image/svg+xml"


@patch("app.routes.album.get_album_by_id")
def test_art_serves_file_when_artpath_exists(mock_get, client, tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0")  # minimal JPEG header
    mock_get.return_value = {**_BASE_ALBUM, "artpath": str(cover)}
    resp = client.get("/album/1/art")
    assert resp.status_code == 200
    assert "image/jpeg" in resp.content_type


@patch("app.routes.album.get_album_by_id")
def test_art_has_no_cache_header(mock_get, client, tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0")
    mock_get.return_value = {**_BASE_ALBUM, "artpath": str(cover)}
    resp = client.get("/album/1/art")
    assert "no-cache" in resp.headers.get("Cache-Control", "")


@patch("app.routes.album.subprocess.run")
@patch("app.routes.album.FLAC")
@patch("app.routes.album.get_album_tracks")
def test_fix_art_success(mock_tracks, mock_flac_cls, mock_run, client, tmp_path):
    flac_file = tmp_path / "01.flac"
    flac_file.touch()
    mock_tracks.return_value = [
        {"track": 1, "title": "Starman", "path": str(tmp_path / "01.flac")}
    ]
    mock_audio = MagicMock()
    mock_audio.pictures = [MagicMock()]
    mock_flac_cls.return_value = mock_audio
    mock_run.return_value.returncode = 0

    resp = client.post("/album/1/fix-art")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    mock_audio.clear_pictures.assert_called_once()
    mock_audio.save.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "fetchart" in args
    assert "id:1" in args


@patch("app.routes.album.get_album_tracks", return_value=[])
def test_fix_art_returns_404_when_no_tracks(mock_tracks, client):
    resp = client.post("/album/1/fix-art")
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


@patch("app.routes.album.subprocess.run")
@patch("app.routes.album.FLAC")
@patch("app.routes.album.get_album_tracks")
def test_fix_art_returns_error_when_beet_fails(mock_tracks, mock_flac_cls, mock_run, client, tmp_path):
    flac_file = tmp_path / "01.flac"
    flac_file.touch()
    mock_tracks.return_value = [
        {"track": 1, "title": "Starman", "path": str(tmp_path / "01.flac")}
    ]
    mock_audio = MagicMock()
    mock_audio.pictures = []
    mock_flac_cls.return_value = mock_audio
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "fetchart: no art found"
    mock_run.return_value.stdout = ""

    resp = client.post("/album/1/fix-art")

    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert "no art found" in data["error"]


@patch("app.routes.album.subprocess.run")
@patch("app.routes.album.FLAC")
@patch("app.routes.album.get_album_tracks")
def test_fix_art_skips_clear_when_no_pictures(mock_tracks, mock_flac_cls, mock_run, client, tmp_path):
    flac_file = tmp_path / "01.flac"
    flac_file.touch()
    mock_tracks.return_value = [
        {"track": 1, "title": "Starman", "path": str(tmp_path / "01.flac")}
    ]
    mock_audio = MagicMock()
    mock_audio.pictures = []  # no embedded art
    mock_flac_cls.return_value = mock_audio
    mock_run.return_value.returncode = 0

    resp = client.post("/album/1/fix-art")

    assert resp.status_code == 200
    mock_audio.clear_pictures.assert_not_called()
    mock_audio.save.assert_not_called()
