import os
from unittest.mock import patch

NEW_LOG = (
    "2026-05-01 12:00:00 | nomatch | /media/music/.beet-stage/Beatles - Let It Be\n"
    "2026-05-02 09:30:00 | skipped | /media/downloads/complete/music/Humble Pie\n"
)

OLD_LOG = "2026-05-01 12:00:00 | /media/music/.beet-stage/Old Format Album\n"


def _setup(cfg, tmp_path, content=NEW_LOG):
    log_path = tmp_path / "import-failed.log"
    log_path.write_text(content)
    cfg.IMPORT_FAILED_LOG = str(log_path)
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")
    return log_path


def test_failed_lists_entries(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path)
    resp = client.get("/failed")
    assert resp.status_code == 200
    assert b"Let It Be" in resp.data
    assert b"Humble Pie" in resp.data


def test_failed_backward_compat_old_format(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path, OLD_LOG)
    resp = client.get("/failed")
    assert resp.status_code == 200
    assert b"Old Format Album" in resp.data


def test_failed_empty_log(client, tmp_path):
    import app.config as cfg

    cfg.IMPORT_FAILED_LOG = str(tmp_path / "import-failed.log")
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")
    resp = client.get("/failed")
    assert resp.status_code == 200


def test_failed_filter_nomatch(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path)
    resp = client.get("/failed?type=nomatch")
    assert resp.status_code == 200
    assert b"Let It Be" in resp.data
    assert b"Humble Pie" not in resp.data


def test_failed_filter_skipped(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path)
    resp = client.get("/failed?type=skipped")
    assert resp.status_code == 200
    assert b"Humble Pie" in resp.data
    assert b"Let It Be" not in resp.data


def test_failed_dismiss_uses_sidecar(client, tmp_path):
    import app.config as cfg

    log_path = _setup(cfg, tmp_path)
    dismissed_path = tmp_path / "import-failed-dismissed.log"

    full_line = "2026-05-01 12:00:00 | nomatch | /media/music/.beet-stage/Beatles - Let It Be"
    resp = client.post("/failed/dismiss", data={"line": full_line})
    assert resp.status_code == 302
    # Original log is untouched
    assert "Let It Be" in log_path.read_text()
    # Sidecar records the full line
    assert full_line in dismissed_path.read_text()
    # Dismissed entry no longer appears in the view
    resp = client.get("/failed")
    assert b"Let It Be" not in resp.data
    assert b"Humble Pie" in resp.data


def test_failed_requeue_creates_path_file(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path)
    cfg.IMPORT_QUEUE_DIR = str(tmp_path / "import-queue")
    os.makedirs(cfg.IMPORT_QUEUE_DIR, exist_ok=True)

    resp = client.post(
        "/failed/requeue",
        data={
            "path": "/media/downloads/complete/music/Humble Pie",
            "line": "2026-05-02 09:30:00 | skipped | /media/downloads/complete/music/Humble Pie",
        },
    )
    assert resp.status_code == 302

    files = list(os.scandir(cfg.IMPORT_QUEUE_DIR))
    assert len(files) == 1
    lines = open(files[0].path).read().splitlines()
    assert lines[0] == "/media/downloads/complete/music/Humble Pie"
    assert lines[1] == "--noincremental"


def test_failed_requeue_auto_dismisses(client, tmp_path):
    import app.config as cfg

    _setup(cfg, tmp_path)
    cfg.IMPORT_QUEUE_DIR = str(tmp_path / "import-queue")
    os.makedirs(cfg.IMPORT_QUEUE_DIR, exist_ok=True)

    expected_line = "2026-05-02 09:30:00 | skipped | /media/downloads/complete/music/Humble Pie"
    resp = client.post(
        "/failed/requeue",
        data={
            "path": "/media/downloads/complete/music/Humble Pie",
            "line": expected_line,
        },
    )
    assert resp.status_code == 302
    # Sidecar records the full line
    dismissed_path = tmp_path / "import-failed-dismissed.log"
    assert expected_line in dismissed_path.read_text()

    # Re-queued entry must not appear on the failed page
    resp = client.get("/failed")
    assert resp.status_code == 200
    assert b"Humble Pie" not in resp.data
    # Other entries remain visible
    assert b"Let It Be" in resp.data


@patch("app.routes.failed.is_locked", return_value=True)
def test_failed_requeue_blocked_when_locked(mock_lock, client):
    resp = client.post("/failed/requeue", data={"path": "/some/path", "line": "some line"})
    assert resp.status_code == 409


ERROR_LOG = (
    "2026-05-20 10:00:00 | nomatch | /media/downloads/complete/music/Beatles - Let It Be\n"
    "2026-05-20 11:00:00 | error | /media/downloads/complete/music/Beck - Sea Change\n"
)


def test_failed_error_kind_shown_in_all_view(client, tmp_path):
    import app.config as cfg
    log_path = tmp_path / "import-failed.log"
    log_path.write_text(ERROR_LOG)
    cfg.IMPORT_FAILED_LOG = str(log_path)
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")

    resp = client.get("/failed")
    assert resp.status_code == 200
    assert b"Sea Change" in resp.data


def test_failed_filter_error_shows_only_error_entries(client, tmp_path):
    import app.config as cfg
    log_path = tmp_path / "import-failed.log"
    log_path.write_text(ERROR_LOG)
    cfg.IMPORT_FAILED_LOG = str(log_path)
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")

    resp = client.get("/failed?type=error")
    assert resp.status_code == 200
    data = resp.data.decode()
    assert "Sea Change" in data
    assert "Let It Be" not in data


def test_failed_error_kind_in_counts(client, tmp_path):
    import app.config as cfg
    log_path = tmp_path / "import-failed.log"
    log_path.write_text(ERROR_LOG)
    cfg.IMPORT_FAILED_LOG = str(log_path)
    cfg.IMPORT_FAILED_DISMISSED_LOG = str(tmp_path / "import-failed-dismissed.log")

    resp = client.get("/failed")
    data = resp.data.decode()
    # The error count of 1 must appear alongside a filter label
    assert "error" in data.lower()


# ---------------------------------------------------------------------------
# dismiss-by-path
# ---------------------------------------------------------------------------

def test_dismiss_by_path_removes_matching_entry(client, tmp_path, monkeypatch):
    log = tmp_path / "import.log"
    log.write_text("2026-01-01 | nomatch | /data/downloads/some/album\n")
    dismissed = tmp_path / "dismissed.log"
    monkeypatch.setattr("app.config.IMPORT_FAILED_LOG", str(log))
    monkeypatch.setattr("app.config.IMPORT_FAILED_DISMISSED_LOG", str(dismissed))
    resp = client.post("/failed/dismiss-by-path", data={"path": "/data/downloads/some/album"})
    assert resp.status_code == 204
    assert "2026-01-01 | nomatch | /data/downloads/some/album" in dismissed.read_text()


def test_dismiss_by_path_no_match_returns_204(client, tmp_path, monkeypatch):
    log = tmp_path / "import.log"
    log.write_text("2026-01-01 | nomatch | /data/downloads/other/album\n")
    dismissed = tmp_path / "dismissed.log"
    monkeypatch.setattr("app.config.IMPORT_FAILED_LOG", str(log))
    monkeypatch.setattr("app.config.IMPORT_FAILED_DISMISSED_LOG", str(dismissed))
    resp = client.post("/failed/dismiss-by-path", data={"path": "/data/downloads/some/album"})
    assert resp.status_code == 204
    assert not dismissed.exists()


def test_dismiss_by_path_empty_path_returns_204(client):
    resp = client.post("/failed/dismiss-by-path", data={"path": ""})
    assert resp.status_code == 204


def test_dismiss_by_path_missing_log_returns_204(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.IMPORT_FAILED_LOG", str(tmp_path / "nonexistent.log"))
    resp = client.post("/failed/dismiss-by-path", data={"path": "/data/downloads/some/album"})
    assert resp.status_code == 204
