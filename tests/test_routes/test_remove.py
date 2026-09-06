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


_JSON = {"Accept": "application/json"}


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
@patch("app.routes.remove.run_beet_command")
def test_remove_returns_json_when_the_client_asks_for_it(mock_run, mock_album, client):
    """The library page deletes in place, so it needs a JSON answer, not a redirect."""
    mock_run.return_value.returncode = 0

    resp = client.post("/remove/1", headers=_JSON)

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
@patch("app.routes.remove.run_beet_command")
def test_form_post_still_redirects(mock_run, mock_album, client):
    mock_run.return_value.returncode = 0

    resp = client.post("/remove/1", headers={"Accept": "text/html"})

    assert resp.status_code == 302


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
@patch("app.routes.remove.run_beet_command")
def test_remove_reports_503_while_an_import_holds_the_lock(mock_run, mock_album, client):
    from app.pipeline.importer import BeetBusy

    mock_run.side_effect = BeetBusy("import running")

    resp = client.post("/remove/1", headers=_JSON)

    assert resp.status_code == 503
    assert "import" in resp.get_json()["error"].lower()


@patch("app.routes.remove.get_album_by_id", return_value=MOCK_ALBUM)
@patch("app.routes.remove.run_beet_command")
def test_remove_surfaces_beet_failure(mock_run, mock_album, client):
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "no such album"
    mock_run.return_value.stdout = ""

    resp = client.post("/remove/1", headers=_JSON)

    assert resp.status_code == 500
    assert "no such album" in resp.get_json()["error"]


@patch("app.routes.remove.get_album_by_id", return_value=None)
def test_remove_missing_album_returns_json_404(mock_album, client):
    resp = client.post("/remove/999", headers=_JSON)

    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
