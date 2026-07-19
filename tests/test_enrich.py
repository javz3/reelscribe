import json

from reelscribe.enrich import build_bundle, collect_pending
from reelscribe.library import Library


def seeded_lib(tmp_path):
    lib = Library(tmp_path / "lib")
    lib.ensure_dirs()
    (lib.transcripts / "001_A_1.txt").write_text("# Duration: 10.0s\n\n[0s-2s]hi\n")
    (lib.meta_dir / "001.json").write_text(json.dumps({"description": "the caption"}))
    (lib.enrich_dir / "001.json").write_text(json.dumps({
        "number": 1, "url": "u", "video_id": "1", "uploader": "A", "title": "T",
        "duration": 10, "has_speech": True,
        "files": {"transcript": "001_A_1.txt"}, "enriched": False}))
    (lib.enrich_dir / "002.json").write_text(json.dumps({
        "number": 2, "url": "u2", "video_id": "2", "uploader": "B", "title": "T2",
        "duration": 5, "has_speech": False, "files": {}, "enriched": True}))
    lib.readme.write_text("# Lib\n## Neck stuff\n## Library Stats\n")
    return lib


def test_collect_pending_skips_enriched(tmp_path):
    lib = seeded_lib(tmp_path)
    pending = collect_pending(lib)
    assert [p["number"] for p in pending] == [1]


def test_build_bundle(tmp_path):
    lib = seeded_lib(tmp_path)
    out = build_bundle(lib)
    bundle = json.loads((out / "ENRICH-BUNDLE.json").read_text(encoding="utf-8"))
    assert len(bundle["reels"]) == 1
    reel = bundle["reels"][0]
    assert "hi" in reel["transcript"]
    assert reel["caption"] == "the caption"
    prompt = (out / "ENRICH-PROMPT.md").read_text(encoding="utf-8")
    assert "- Neck stuff" in prompt
    assert "- Library Stats" not in prompt
    assert "Pending reels: 1" in prompt
