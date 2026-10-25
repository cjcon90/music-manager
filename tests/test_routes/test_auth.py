from tests.conftest import TEST_PASSWORD


def test_logged_out_redirects_to_login_with_next(anon_client):
    resp = anon_client.get("/queue")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?next=/queue"


def test_login_sets_long_lived_session_and_follows_next(anon_client):
    resp = anon_client.post(
        "/login?next=/queue", data={"username": "cjcon90", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/queue"
    assert "Expires=" in resp.headers["Set-Cookie"]
    assert anon_client.get("/queue").status_code == 200


def test_wrong_password_rejected(anon_client):
    resp = anon_client.post("/login", data={"username": "cjcon90", "password": "nope"})
    assert resp.status_code == 401
    assert anon_client.get("/queue").status_code == 302


def test_next_cannot_leave_the_site(anon_client):
    resp = anon_client.post(
        "/login?next=//evil.example", data={"username": "cjcon90", "password": TEST_PASSWORD}
    )
    assert resp.headers["Location"] == "/"
