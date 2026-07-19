"""reelscribe command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config
from .library import Library, dedupe, extract_urls


def _resolve_library(args) -> Library:
    cfg = config.load()
    root = getattr(args, "library", None) or cfg.get("library")
    if not root:
        sys.exit("No library configured. Run:  reelscribe config --library /path/to/library\n"
                 "(the folder that contains — or will contain — Videos/)")
    return Library(Path(root).expanduser())


def _cli_sink(result, message: str) -> None:
    num = f"#{result.number}" if result.number else "—"
    print(f"  [{num:>5}] {result.stage:<10} {message}", flush=True)


def cmd_add(args) -> int:
    from .pipeline import process_batch
    cfg = config.load()
    lib = _resolve_library(args)
    urls = dedupe(args.urls)
    print(f"reelscribe: {len(urls)} URL(s) → {lib.root}")
    results = process_batch(
        urls, lib,
        whisper_model=args.model or cfg.get("whisper_model", "small.en"),
        language=args.language,
        cookies_from_browser=args.cookies_from_browser or cfg.get("cookies_from_browser"),
        sink=_cli_sink,
    )
    done = [r for r in results if r.status == "done"]
    skipped = [r for r in results if r.status == "skipped"]
    errors = [r for r in results if r.status == "error"]
    print(f"\ndone: {len(done)}   skipped (duplicates): {len(skipped)}   errors: {len(errors)}")
    for r in skipped:
        print(f"  skipped {r.url} — {r.error}")
    for r in errors:
        print(f"  ERROR   {r.url} — {r.error}")
    if done:
        print("\nDrafts written. Next: `reelscribe bundle` to hand the judgment pass to your LLM.")
    return 1 if errors else 0


def cmd_batch(args) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    urls = extract_urls(text)
    if not urls:
        sys.exit(f"No URLs found in {args.file}")
    args.urls = urls
    return cmd_add(args)


def cmd_status(args) -> int:
    lib = _resolve_library(args)
    from .enrich import collect_pending
    s = lib.stats()
    pending = len(collect_pending(lib))
    print(f"library      {s['root']}")
    print(f"videos       {s['videos']}")
    print(f"audio        {s['audio']}")
    print(f"transcripts  {s['transcripts']}")
    print(f"documents    {s['documents']}")
    print(f"thumbnails   {s['thumbnails']}")
    print(f"next number  {s['next_number']}")
    print(f"pending enrichment  {pending}")
    return 0


def cmd_bundle(args) -> int:
    from .enrich import build_bundle, collect_pending
    lib = _resolve_library(args)
    pending = collect_pending(lib)
    if not pending:
        print("Nothing pending enrichment.")
        return 0
    out = build_bundle(lib, Path(args.out) if args.out else None)
    print(f"{len(pending)} reel(s) bundled → {out}")
    print("Feed ENRICH-PROMPT.md + ENRICH-BUNDLE.json to your LLM (or Claude Code).")
    return 0


def cmd_enrich(args) -> int:
    from .llm import run_enrichment
    lib = _resolve_library(args)
    run_enrichment(lib, model=args.model, limit=args.limit or 0, engine=args.engine)
    return 0


def cmd_config(args) -> int:
    if args.library:
        config.set_value("library", str(Path(args.library).expanduser().resolve()))
    if args.model:
        config.set_value("whisper_model", args.model)
    if args.cookies_from_browser is not None:
        config.set_value("cookies_from_browser", args.cookies_from_browser or None)
    cfg = config.load()
    for k, v in cfg.items():
        print(f"{k} = {v}")
    print(f"\n(config file: {config.CONFIG_PATH})")
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn

        from .webapp import create_app
    except ImportError:
        sys.exit("Web UI needs the extras:  pip install 'reelscribe[web]'")
    lib = _resolve_library(args)
    cfg = config.load()
    app = create_app(lib, cfg)
    print(f"reelscribe web UI → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--library", help="library root (overrides config)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="reelscribe",
        description="Social-media video URL → offline library: video + audio + "
                    "transcript + thumbnail + draft doc.")
    ap.add_argument("--version", action="version", version=f"reelscribe {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="ingest one or more URLs")
    p.add_argument("urls", nargs="+")
    p.add_argument("--model", help="faster-whisper model (default from config: small.en)")
    p.add_argument("--language", help="force transcription language (e.g. ko, ur)")
    p.add_argument("--cookies-from-browser", help="browser to read login cookies from "
                   "(chrome/firefox/edge) — needed for Instagram/TikTok")
    _add_common(p)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("batch", help="ingest every URL found in a text/markdown file")
    p.add_argument("file")
    p.add_argument("--model")
    p.add_argument("--language")
    p.add_argument("--cookies-from-browser")
    _add_common(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("status", help="library statistics")
    _add_common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("bundle", help="build the Stage-2 enrichment bundle for your LLM")
    p.add_argument("--out", help="output folder (default: <library>/.reelscribe/enrich/bundle)")
    _add_common(p)
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("enrich", help="finalise pending drafts with Claude — via your "
                       "Claude Code subscription login (--engine claude-cli) or the API")
    p.add_argument("--engine", choices=["api", "claude-cli"], default="api",
                   help="api = Anthropic SDK (API key/Console); "
                        "claude-cli = Claude Code headless mode (subscription login)")
    p.add_argument("--model", help="model override (API: model ID, default claude-opus-4-8; "
                                   "claude-cli: e.g. 'opus'/'sonnet', default = CLI default)")
    p.add_argument("--limit", type=int, help="enrich at most N reels")
    _add_common(p)
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("config", help="show or set configuration")
    p.add_argument("--library", help="set the default library root")
    p.add_argument("--model", help="set the default whisper model")
    p.add_argument("--cookies-from-browser", help="set default browser for cookies ('' to clear)")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("serve", help="run the local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    _add_common(p)
    p.set_defaults(func=cmd_serve)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
