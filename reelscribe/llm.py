"""Stage-2 enrichment via the Claude API (v2 feature, opt-in).

`reelscribe enrich` turns 🔶 raw drafts into finished docs: one API call per
reel, returning a structured result (final doc markdown + category placement +
star verdict + an index-row hook). The library README is NOT edited — suggested
table rows land in ENRICH-REPORT.md for review, keeping the human/LLM curator
in charge of the index.

Requires:  pip install 'reelscribe[llm]'   and an Anthropic credential
(ANTHROPIC_API_KEY, or an `ant auth login` profile).
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

from .enrich import collect_pending
from .library import Library

DEFAULT_MODEL = "claude-opus-4-8"

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string",
                  "description": "Concise doc title (no hashtags, no view counts)"},
        "doc_markdown": {
            "type": "string",
            "description": "The COMPLETE final markdown document, ready to write to disk verbatim",
        },
        "categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 category names, drawn from the provided taxonomy where possible",
        },
        "star": {"type": "boolean", "description": "True only if genuinely a standout"},
        "star_reason": {"type": "string",
                        "description": "Why it earned (or didn't earn) a star, one sentence"},
        "hook": {"type": "string", "description": "Short index-table hook text, under 12 words"},
        "tier": {
            "type": "string",
            "enum": ["verbatim", "inferred", "blueprint"],
            "description": "verbatim = rich transcript; inferred = silent, worked from "
                           "caption/thumbnail; blueprint = caption-only",
        },
    },
    "required": ["title", "doc_markdown", "categories", "star", "star_reason", "hook", "tier"],
    "additionalProperties": False,
}

SYSTEM_TEMPLATE = """You are the enrichment stage of reelscribe, a tool that files social-media \
exercise/physio videos into a searchable offline knowledge library.

You receive one reel's raw materials (metadata, platform caption, timestamped Whisper transcript) \
and produce the finished markdown document for the library.

Rules — these are hard constraints:
- Ground every claim in the transcript or caption provided. NEVER invent protocol details \
(hold times, reps, doses, frequencies) that are not in the source material.
- Quote the source: include at least one direct quote from the transcript (or caption if silent) \
in a "## Key Concept" section.
- Silent/music-only reels (empty or lyrics-only transcript): keep an explicit "## Audio Note" \
section, work only from the caption, and mark the doc tier "inferred". If the caption doesn't \
fully specify the exercise, say so plainly and point the reader at the video.
- Keep the deterministic header fields from the draft exactly as given (Source URL, Creator, \
Duration, Video file).
- Structure: title heading, header fields, ## What This Is, ## Key Concept (or ## Audio Note), \
## The Exercise (step-by-step) when steps exist, ## Cross-Reference (only if related docs are \
listed in the input — never invent references), ## Tags.
- Be honest about marketing: if the reel is primarily selling something (a course, an app, \
an assessment), note it. Flag weak or contested evidence bases rather than endorsing claims.
- Stars (⭐) are rare: reserve for reels that are unusually complete, evidence-backed, or fill \
a gap in the library.

Category taxonomy of the target library (prefer these; propose a new one only when nothing fits):
{taxonomy}

Example documents from this library (match their depth and voice):

{examples}"""


def _example_docs(lib: Library, max_docs: int = 2, max_chars: int = 3500) -> str:
    """Pick up to two finished docs (no RAW DRAFT banner) as few-shot style anchors."""
    finished = []
    if lib.documents.is_dir():
        for f in sorted(lib.documents.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if "RAW DRAFT" not in text and 800 < len(text) < max_chars:
                finished.append(text)
            if len(finished) >= max_docs:
                break
    if not finished:
        return "(no finished examples available yet — use the structure rules above)"
    return "\n\n---\n\n".join(finished)


def build_system_prompt(lib: Library) -> str:
    cats = lib.categories()
    taxonomy = "\n".join(f"- {c}" for c in cats) if cats else "(none defined yet)"
    return SYSTEM_TEMPLATE.format(taxonomy=taxonomy, examples=_example_docs(lib))


def build_user_prompt(lib: Library, rec: dict) -> str:
    tr_name = rec.get("files", {}).get("transcript", "")
    transcript = ""
    if tr_name:
        tp = lib.transcripts / tr_name
        if tp.exists():
            transcript = tp.read_text(encoding="utf-8")
    caption = ""
    meta_path = lib.meta_dir / f"{rec['number']:0{lib.width()}d}.json"
    if meta_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            caption = json.loads(meta_path.read_text(encoding="utf-8")).get("description", "")
    draft = ""
    doc_name = rec.get("files", {}).get("document", "")
    if doc_name and (lib.documents / doc_name).exists():
        draft = (lib.documents / doc_name).read_text(encoding="utf-8")

    return (
        f"Reel #{rec['number']}\n"
        f"Creator: {rec.get('uploader', 'unknown')}\n"
        f"Duration: {rec.get('duration', 0):.0f}s\n"
        f"Has speech: {rec.get('has_speech')}\n\n"
        f"## Current draft doc (keep its deterministic header fields)\n\n{draft}\n\n"
        f"## Platform caption (verbatim)\n\n{caption or '(none)'}\n\n"
        f"## Whisper transcript (timestamped)\n\n{transcript or '(empty — silent or music-only)'}\n"
    )


def enrich_reel(client, lib: Library, rec: dict, system_prompt: str,
                model: str = DEFAULT_MODEL) -> dict:
    """One API call → validated result dict (see RESULT_SCHEMA)."""
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": system_prompt,
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        messages=[{"role": "user", "content": build_user_prompt(lib, rec)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the request (stop_reason=refusal)")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("output truncated (stop_reason=max_tokens) — doc too long")
    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)
    result["_usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return result


def apply_result(lib: Library, rec: dict, result: dict) -> Path:
    """Write the final doc over the draft and mark the reel enriched."""
    doc_name = rec.get("files", {}).get("document")
    if not doc_name:
        raise ValueError(f"reel #{rec['number']} has no draft document recorded")
    doc_path = lib.documents / doc_name
    doc_path.write_text(result["doc_markdown"].rstrip() + "\n", encoding="utf-8")

    rec_path = lib.enrich_dir / f"{rec['number']:0{lib.width()}d}.json"
    rec.update({
        "enriched": True,
        "enriched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "enrichment": {
            "title": result["title"], "categories": result["categories"],
            "star": result["star"], "star_reason": result["star_reason"],
            "hook": result["hook"], "tier": result["tier"],
            "model": result.get("_model", ""),
        },
    })
    rec_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc_path


def write_report(lib: Library, entries: list[dict]) -> Path:
    """ENRICH-REPORT.md: ready-to-paste README rows, grouped by category."""
    by_cat: dict[str, list[dict]] = {}
    for e in entries:
        for cat in e["categories"] or ["(uncategorised)"]:
            by_cat.setdefault(cat, []).append(e)

    lines = [
        "# reelscribe enrichment report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Enriched: {len(entries)} reel(s)",
        "",
        "Suggested README table rows (review, then paste into the matching section —",
        "reelscribe does not edit your README):",
        "",
    ]
    for cat, items in by_cat.items():
        lines.append(f"## {cat}")
        lines.append("")
        for e in items:
            star = "⭐ " if e["star"] else ""
            lines.append(
                f"| {e['number']} | {star}[{e['title']}](Videos/Document/{e['doc']}) "
                f"| {e['uploader']} | {e['hook']} |"
            )
        lines.append("")
    starred = [e for e in entries if e["star"]]
    if starred:
        lines.append("## ⭐ Standouts")
        lines.append("")
        lines += [f"- **#{e['number']}** {e['title']} — {e['star_reason']}" for e in starred]
        lines.append("")
    out = lib.enrich_dir / "ENRICH-REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def run_enrichment(lib: Library, model: str = DEFAULT_MODEL, limit: int = 0,
                   log=print) -> int:
    """CLI entry: enrich all pending reels. Returns count enriched."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit(
            "The enrich command needs the Anthropic SDK:  pip install 'reelscribe[llm]'"
        ) from None

    pending = collect_pending(lib)
    if limit:
        pending = pending[:limit]
    if not pending:
        log("Nothing pending enrichment.")
        return 0

    client = anthropic.Anthropic()
    system_prompt = build_system_prompt(lib)
    log(f"Enriching {len(pending)} reel(s) with {model} …")

    entries, total_in, total_out = [], 0, 0
    for rec in pending:
        n = rec["number"]
        try:
            result = enrich_reel(client, lib, rec, system_prompt, model=model)
        except anthropic.AuthenticationError:
            raise SystemExit(
                "No valid Anthropic credential. Set ANTHROPIC_API_KEY or run `ant auth login`."
            ) from None
        except anthropic.RateLimitError:
            log(f"  #{n}: rate limited — waiting 30s and retrying once")
            time.sleep(30)
            result = enrich_reel(client, lib, rec, system_prompt, model=model)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError,
                json.JSONDecodeError, StopIteration) as e:
            log(f"  #{n}: FAILED — {e}")
            continue

        result["_model"] = model
        doc_path = apply_result(lib, rec, result)
        u = result["_usage"]
        total_in += u["input_tokens"] + u["cache_read_input_tokens"]
        total_out += u["output_tokens"]
        star = " ⭐" if result["star"] else ""
        log(f"  #{n}: {result['title']}{star} → {doc_path.name}  "
            f"[{result['tier']}; {', '.join(result['categories'])}]")
        entries.append({
            "number": n, "title": result["title"], "uploader": rec.get("uploader", ""),
            "doc": doc_path.name, "categories": result["categories"],
            "star": result["star"], "star_reason": result["star_reason"],
            "hook": result["hook"],
        })

    if entries:
        report = write_report(lib, entries)
        log(f"\n{len(entries)} doc(s) finalised. Report → {report}")
        log(f"tokens: ~{total_in} in / ~{total_out} out")
    return len(entries)
