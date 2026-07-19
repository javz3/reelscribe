"""Stage-2 handoff: build an enrichment bundle for an LLM/human editor.

`reelscribe bundle` collects every un-enriched reel (``.reelscribe/enrich/*.json``
with ``"enriched": false``) into one folder containing:

    ENRICH-BUNDLE.json   all pending reels: metadata + caption + full transcript
    ENRICH-PROMPT.md     instructions + the library's category taxonomy

Feed both files (plus the library README) to your LLM of choice — or open a
Claude Code session in the library and say "process the reelscribe bundle".
v2 will optionally call the Claude API directly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .library import Library

PROMPT_TEMPLATE = """# reelscribe enrichment bundle — instructions

Generated: {ts}
Library: {root}
Pending reels: {count}

For each reel in `ENRICH-BUNDLE.json`:

1. Rewrite its draft doc in `Videos/Document/` to final form:
   - Replace the `TODO-enrichment` sections (What This Is, steps, cross-references, tags).
   - Keep every deterministic field (source URL, creator, duration, video file).
   - Quote only from the transcript/caption included in the bundle — do not invent
     protocol details (holds, reps, doses) that are not in the source.
   - Silent reels: keep the Audio Note and work from the caption; mark the doc
     Inferred-tier if instructions are not fully recoverable.
   - Remove the 🔶 RAW DRAFT banner once done.
2. Decide category placement using the taxonomy below and add the reel to the
   library README's matching table(s).
3. Flag standouts with ⭐ only where genuinely warranted; note evidence caveats.
4. Update the README's count + Library Stats.
5. Set `"enriched": true` in the reel's `.reelscribe/enrich/NNN.json`.

## Category taxonomy (from the library README)

{taxonomy}
"""


def collect_pending(lib: Library) -> list[dict]:
    pending = []
    if not lib.enrich_dir.is_dir():
        return pending
    for f in sorted(lib.enrich_dir.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not rec.get("enriched"):
            pending.append(rec)
    return pending


def build_bundle(lib: Library, out_dir: Path = None) -> Path:
    out = Path(out_dir) if out_dir else (lib.enrich_dir / "bundle")
    out.mkdir(parents=True, exist_ok=True)
    pending = collect_pending(lib)

    reels = []
    for rec in pending:
        item = dict(rec)
        tr = rec.get("files", {}).get("transcript")
        if tr:
            tp = lib.transcripts / tr
            item["transcript"] = tp.read_text(encoding="utf-8") if tp.exists() else ""
        meta_files = sorted(lib.meta_dir.glob(f"{rec['number']:0{lib.width()}d}.json"))
        if meta_files:
            try:
                meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
                item["caption"] = meta.get("description", "")
            except (json.JSONDecodeError, OSError):
                pass
        reels.append(item)

    (out / "ENRICH-BUNDLE.json").write_text(
        json.dumps({"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "library": str(lib.root), "reels": reels},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")

    cats = lib.categories()
    if cats:
        taxonomy = "\n".join(f"- {c}" for c in cats)
    else:
        taxonomy = "(no README found — propose a taxonomy)"
    (out / "ENRICH-PROMPT.md").write_text(
        PROMPT_TEMPLATE.format(ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                               root=lib.root, count=len(reels), taxonomy=taxonomy),
        encoding="utf-8")
    return out
