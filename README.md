# reelscribe

Turn social-media video URLs into a **searchable, offline knowledge library** —
video + audio + timestamped transcript + thumbnail + a draft markdown doc per clip,
all filed into a consistent folder structure with continuous numbering.

Built for the workflow of collecting exercise/physio reels, but works for any
short-form video you want to keep and search: lectures, recipes, tutorials.

```
URL ──► metadata ──► dedup check ──► video ──► audio ──► thumbnail
                                   ──► Whisper transcript ──► draft doc
```

- **Any platform yt-dlp supports** (~1,800 sites): Facebook, YouTube, Instagram,
  TikTok, X/Twitter, Vimeo, Reddit… Instagram/TikTok usually need
  `--cookies-from-browser chrome` (login wall).
- **Fully local** — transcription runs on your CPU via
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper); no API keys, no cloud.
- **Cross-platform** — Linux, macOS, Windows, WSL. No ffmpeg required
  (video and audio are downloaded as separate streams).
- **Two-stage by design** — Stage 1 (this tool) is deterministic extraction.
  Stage 2 — cross-referencing, quality judgment, categorisation — is where an
  LLM or a human adds value; `reelscribe bundle` packages everything Stage 2 needs.

## Install

```bash
pip install reelscribe            # core (CLI)
pip install 'reelscribe[web]'     # + local web UI
```

Or from source: `pip install -e '.[web,dev]'`

First transcription downloads the Whisper model (~470 MB for `small.en`).

## Quick start

```bash
# one-time: point at your library folder (created if missing)
reelscribe config --library ~/Reels

# ingest
reelscribe add https://www.facebook.com/share/r/EXAMPLE/
reelscribe batch links.txt        # any text/markdown file containing URLs

# see where you are
reelscribe status

# package everything pending for the judgment pass (LLM or human)
reelscribe bundle
```

### Web UI

```bash
reelscribe serve                  # → http://127.0.0.1:8765
```

Paste URLs, watch per-stage progress, see library stats. Single page, no build
step, runs entirely on your machine.

## Library layout

```
<library>/
├── README.md                     your index (reelscribe reads its ## headings
│                                 as the category taxonomy for Stage 2)
└── Videos/
    ├── 001_Creator Name_<video_id>.mp4
    ├── Audio/
    │   ├── 001_Creator Name_<video_id>.m4a
    │   └── Transcripts/
    │       └── 001_Creator Name_<video_id>.txt      # [ 12.34s- 15.67s]text
    ├── Thumbnails/001.jpg
    └── Document/001_short_slug_creator.md           # draft doc, 🔶 banner
```

Numbering continues from the highest existing file — safe to point at a library
you built by hand. Re-adding a URL that's already in the library is detected by
platform video-ID and skipped.

## The draft doc

Deterministic fields are filled in (source link, creator, duration, caption,
an auto-selected key quote from the transcript). Judgment sections are marked
`TODO-enrichment`. Silent/music-only clips (detected via Whisper's VAD) get an
explicit **Audio Note** so nobody mistakes a lyrics fragment for instructions.

## Stage 2: enrichment

Two ways to run the judgment pass:

**A. Hand off (`reelscribe bundle`)** — writes `ENRICH-BUNDLE.json` (all pending
reels with full transcripts + captions) and `ENRICH-PROMPT.md` (instructions +
your README's taxonomy). Hand both to your LLM of choice — e.g. open the library
in Claude Code and say *"process the reelscribe bundle"*.

**B. Built-in (`reelscribe enrich`)** — calls the Claude API directly, one
request per pending reel:

```bash
pip install 'reelscribe[llm]'
export ANTHROPIC_API_KEY=sk-ant-...   # or `ant auth login`
reelscribe enrich                      # all pending
reelscribe enrich --limit 3            # try a few first
reelscribe enrich --model claude-sonnet-5   # cheaper model if you prefer
```

Per reel it produces the finished doc (grounded in the transcript/caption — the
prompt forbids inventing protocol details), a category placement from your
taxonomy, a rare-by-design ⭐ verdict, and an index-row hook. Finished docs
replace the drafts in place; **your README is never edited** — suggested table
rows land in `.reelscribe/enrich/ENRICH-REPORT.md` for you to review and paste.
Uses structured outputs (JSON schema-validated), adaptive thinking, and prompt
caching on the shared system prompt. Default model: `claude-opus-4-8`.

## Options

| Flag | Purpose |
|---|---|
| `--library PATH` | per-command library override |
| `--model NAME` | whisper model (`small.en` default; `small` for multilingual, `base.en` for speed) |
| `--language XX` | force transcript language (e.g. `ko`, `ur`) |
| `--cookies-from-browser B` | read login cookies from chrome/firefox/edge (Instagram, TikTok) |

## Roadmap

- ~~Built-in Claude API enrichment step~~ ✅ v2 (`reelscribe enrich`)
- Cross-reference pass: give the enricher sight of related existing docs
- Embedding-based "related clips" suggestions
- Per-platform test fixtures for TikTok / Instagram / X
- Watch-folder / clipboard monitor mode

## License

MIT
