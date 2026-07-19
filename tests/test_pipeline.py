"""Pipeline test with network + Whisper mocked out."""

import json
from pathlib import Path

import pytest

from reelscribe import pipeline, transcribe
from reelscribe.library import Library

INFO = {
    "id": "999888777",
    "title": "Some reel title",
    "uploader": "Dr. Mock",
    "duration": 30,
    "description": "caption text",
    "webpage_url": "https://www.facebook.com/watch/?v=999888777",
    "thumbnail": None,  # skip thumbnail stage
    "extractor_key": "Facebook",
}


@pytest.fixture
def lib(tmp_path):
    return Library(tmp_path / "lib")


@pytest.fixture
def mocked(monkeypatch):
    def fake_fetch(url, cookies_from_browser=None):
        return dict(INFO)

    def fake_download(url, outtmpl, fmt, cookies_from_browser):
        p = Path(outtmpl.replace("%(ext)s", "m4a" if fmt == "bestaudio" else "mp4"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake")
        return p

    def fake_transcribe(audio_path, model_name="small.en", language=None):
        return [{"start": 0.0, "end": 2.0, "text": "Hello neck."}], 30.0

    monkeypatch.setattr(pipeline, "fetch_metadata", fake_fetch)
    monkeypatch.setattr(pipeline, "_download", fake_download)
    monkeypatch.setattr(transcribe, "transcribe_file", fake_transcribe)


def test_process_url_end_to_end(lib, mocked):
    r = pipeline.process_url("https://example.com/x", lib)
    assert r.status == "done", r.error
    assert r.number == 1
    assert (lib.videos / "001_Dr. Mock_999888777.mp4").exists()
    assert (lib.audio / "001_Dr. Mock_999888777.m4a").exists()
    tr = lib.transcripts / "001_Dr. Mock_999888777.txt"
    assert tr.exists() and "Hello neck." in tr.read_text()
    docs = list(lib.documents.glob("001_*.md"))
    assert len(docs) == 1
    assert "RAW DRAFT" in docs[0].read_text(encoding="utf-8")
    rec = json.loads((lib.enrich_dir / "001.json").read_text())
    assert rec["enriched"] is False and rec["has_speech"] is True
    meta = json.loads((lib.meta_dir / "001.json").read_text())
    assert meta["id"] == "999888777"


def test_duplicate_skipped(lib, mocked):
    first = pipeline.process_url("https://example.com/x", lib)
    assert first.status == "done"
    second = pipeline.process_url("https://example.com/x-again", lib)
    assert second.status == "skipped"
    assert "duplicate" in second.error
    assert lib.next_number() == 2  # nothing new written


def test_batch_continues_after_error(lib, mocked, monkeypatch):
    calls = {"n": 0}
    real_fetch = pipeline.fetch_metadata

    def flaky(url, cookies_from_browser=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network down")
        info = dict(INFO)
        info["id"] = f"id{calls['n']}"
        return info

    monkeypatch.setattr(pipeline, "fetch_metadata", flaky)
    results = pipeline.process_batch(["u1", "u2"], lib)
    assert [r.status for r in results] == ["error", "done"]
    assert results[0].error == "network down"
    assert results[1].number == 1
