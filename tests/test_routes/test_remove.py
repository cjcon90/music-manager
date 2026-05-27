from unittest.mock import patch

MOCK_ALBUM = {
    "id": 1,
    "album": "Ziggy Stardust",
    "artist": "David Bowie",
    "year": 1972,
    "tracks": 11,
    "path": "/media/music/David Bowie/Ziggy Stardust (1972)/01.flac",
}


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
def test_remove_confirm_shows_album(mock_album, client):
    resp = client.get("/remove/1")
    assert resp.status_code == 200
    assert b"Ziggy Stardust" in resp.data
    assert b"David Bowie" in resp.data


@patch("app.routes.remove.get_album_by_id", return_value=None)
def test_remove_album_not_found(mock_album, client):
    resp = client.get("/remove/999")
    assert resp.status_code == 404


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
@patch("app.routes.remove.run_beet_command")
def test_remove_post_calls_beet_remove(mock_run, mock_album, client):
    mock_run.return_value.returncode = 0
    resp = client.post("/remove/1")
    assert resp.status_code == 302
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "beet" in call_args
    assert "remove" in call_args
    assert "album_id:1" in " ".join(call_args)
