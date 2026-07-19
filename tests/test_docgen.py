from reelscribe import docgen


INFO = {
    "id": "123456",
    "title": "10K views · 200 reactions | Fix your neck now #neckpain",
    "uploader": "Dr. Test",
    "duration": 75,
    "description": "Do the thing.\nHold 10 seconds.",
    "webpage_url": "https://m.facebook.com/watch/?v=123456&_rdr",
    "extractor_key": "Facebook",
}

SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "First we do this."},
    {"start": 2.0, "end": 4.0, "text": "Then we hold for ten seconds."},
]


def test_draft_with_speech(tmp_path):
    p = tmp_path / "doc.md"
    docgen.write_draft(p, number=7, info=INFO, files={"video": "007_Dr. Test_123456.mp4"},
                       segments=SEGMENTS, has_speech=True)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# Fix your neck now\n")
    assert "RAW DRAFT" in text
    # canonical desktop URL, not the mobile redirect
    assert "https://www.facebook.com/watch/?v=123456" in text
    assert "m.facebook.com" not in text
    assert "**Duration:** 1:15" in text
    assert "Key Concept" in text and "First we do this." in text
    assert "> Do the thing." in text  # caption block
    assert "TODO-enrichment" in text
    assert "Audio Note" not in text


def test_draft_silent(tmp_path):
    p = tmp_path / "doc.md"
    docgen.write_draft(p, number=8, info=INFO, files={}, segments=[], has_speech=False)
    text = p.read_text(encoding="utf-8")
    assert "## Audio Note" in text
    assert "Tier: Inferred" in text
    assert "Key Concept" not in text


def test_key_quote_truncates():
    long = [{"start": 0, "end": 1, "text": "word " * 200}]
    q = docgen._key_quote(long)
    assert len(q) <= 345 and q.endswith("…")
