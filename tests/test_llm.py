"""Enrichment tests with a mocked Anthropic client — no network, no API key."""

import json
from types import SimpleNamespace

import pytest

from reelscribe import llm
from reelscribe.library import Library

RESULT = {
    "title": "Side Isometric for Neck Stiffness",
    "doc_markdown": "# Side Isometric for Neck Stiffness\n\nFinal doc body.\n",
    "categories": ["Neck stuff"],
    "star": True,
    "star_reason": "Clearest mechanism explanation in the library.",
    "hook": "Isometrics calm the nervous system",
    "tier": "verbatim",
}


class FakeClient:
    def __init__(self, stop_reason="end_turn", payload=RESULT):
        self.calls = []
        self._stop = stop_reason
        self._payload = payload
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self._stop,
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                                  cache_read_input_tokens=200),
        )


@pytest.fixture
def lib(tmp_path):
    lib = Library(tmp_path / "lib")
    lib.ensure_dirs()
    lib.readme.write_text("# L\n## Neck stuff\n## Library Stats\n", encoding="utf-8")
    (lib.transcripts / "001_A_1.txt").write_text("# Duration: 10.0s\n\n[0s-2s]push gently\n")
    (lib.meta_dir / "001.json").write_text(json.dumps({"description": "the caption"}))
    (lib.documents / "001_draft_a.md").write_text("# Draft\n\nRAW DRAFT\n")
    (lib.enrich_dir / "001.json").write_text(json.dumps({
        "number": 1, "url": "u", "video_id": "1", "uploader": "Dr. A", "title": "T",
        "duration": 10, "has_speech": True, "enriched": False,
        "files": {"transcript": "001_A_1.txt", "document": "001_draft_a.md"}}))
    return lib


def test_prompts_include_sources(lib):
    system = llm.build_system_prompt(lib)
    assert "- Neck stuff" in system
    rec = json.loads((lib.enrich_dir / "001.json").read_text())
    user = llm.build_user_prompt(lib, rec)
    assert "push gently" in user
    assert "the caption" in user
    assert "RAW DRAFT" in user  # draft included so header fields carry over


def test_enrich_reel_call_shape(lib):
    client = FakeClient()
    rec = json.loads((lib.enrich_dir / "001.json").read_text())
    result = llm.enrich_reel(client, lib, rec, "SYSTEM", model="claude-opus-4-8")
    assert result["title"] == RESULT["title"]
    assert result["_usage"]["output_tokens"] == 500
    call = client.calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in call


def test_enrich_reel_refusal_raises(lib):
    client = FakeClient(stop_reason="refusal")
    rec = json.loads((lib.enrich_dir / "001.json").read_text())
    with pytest.raises(RuntimeError, match="refusal"):
        llm.enrich_reel(client, lib, rec, "SYSTEM")


def test_apply_result_writes_doc_and_marks_enriched(lib):
    rec = json.loads((lib.enrich_dir / "001.json").read_text())
    result = dict(RESULT, _model="claude-opus-4-8")
    path = llm.apply_result(lib, rec, result)
    assert path.read_text(encoding="utf-8").startswith("# Side Isometric")
    updated = json.loads((lib.enrich_dir / "001.json").read_text())
    assert updated["enriched"] is True
    assert updated["enrichment"]["star"] is True
    assert updated["enrichment"]["categories"] == ["Neck stuff"]


def test_write_report(lib):
    entries = [{
        "number": 1, "title": RESULT["title"], "uploader": "Dr. A",
        "doc": "001_draft_a.md", "categories": ["Neck stuff"],
        "star": True, "star_reason": RESULT["star_reason"], "hook": RESULT["hook"],
    }]
    report = llm.write_report(lib, entries)
    text = report.read_text(encoding="utf-8")
    assert "## Neck stuff" in text
    assert "| 1 | ⭐ [Side Isometric" in text
    assert "## ⭐ Standouts" in text


def test_example_docs_skips_drafts(lib):
    (lib.documents / "002_final.md").write_text("# Finished doc\n" + "x" * 900)
    examples = llm._example_docs(lib)
    assert "Finished doc" in examples
    assert "RAW DRAFT" not in examples
