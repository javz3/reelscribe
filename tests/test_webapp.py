import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from reelscribe.library import Library  # noqa: E402
from reelscribe.webapp import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    lib = Library(tmp_path / "lib")
    lib.ensure_dirs()
    app = create_app(lib, {"whisper_model": "small.en"})
    return TestClient(app)


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "reelscribe" in r.text


def test_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["busy"] is False
    assert body["stats"]["videos"] == 0


def test_ingest_no_urls(client):
    r = client.post("/api/ingest", json={"text": "no links here"})
    assert r.status_code == 200
    assert r.json() == {"found": 0, "queued": 0}
