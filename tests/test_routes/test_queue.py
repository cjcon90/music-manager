import os


def test_queue_page_loads(client):
    resp = client.get("/queue")
    assert resp.status_code == 200


def test_queue_add_creates_path_file(client, tmp_path):
    import app.config as cfg

    cfg.IMPORT_QUEUE_DIR = str(tmp_path / "import-queue")
    os.makedirs(cfg.IMPORT_QUEUE_DIR, exist_ok=True)

    resp = client.post("/queue/add", data={"path": "/media/downloads/complete/music/My Album"})
    assert resp.status_code in (200, 302)

    files = os.listdir(cfg.IMPORT_QUEUE_DIR)
    assert len(files) == 1
    assert files[0].endswith(".path")
    content = open(os.path.join(cfg.IMPORT_QUEUE_DIR, files[0])).read()
    assert "/media/downloads/complete/music/My Album" in content


def test_queue_add_rejects_empty_path(client):
    resp = client.post("/queue/add", data={"path": ""})
    assert resp.status_code in (400, 302)
