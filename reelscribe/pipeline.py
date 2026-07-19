"""The deterministic ingestion pipeline (Stage 1).

Per URL:  metadata → dedup check → video download → audio download →
thumbnail → transcript → draft doc → enrichment record.

Every step reports through a ProgressSink so the CLI and the web UI can
render the same events.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from . import docgen, transcribe
from .library import Library, safe_component, slugify

STAGES = ["metadata", "video", "audio", "thumbnail", "transcript", "document"]


@dataclass
class ReelResult:
    url: str
    number: Optional[int] = None
    video_id: str = ""
    uploader: str = ""
    title: str = ""
    duration: float = 0.0
    status: str = "pending"          # pending | running | done | skipped | error
    stage: str = ""                  # last stage reached
    error: str = ""
    files: dict = field(default_factory=dict)
    has_speech: bool = False

    def as_dict(self) -> dict:
        return {
            "url": self.url, "number": self.number, "video_id": self.video_id,
            "uploader": self.uploader, "title": self.title,
            "duration": self.duration, "status": self.status, "stage": self.stage,
            "error": self.error, "files": self.files, "has_speech": self.has_speech,
        }


ProgressSink = Callable[[ReelResult, str], None]
"""Called as sink(result, message) after every stage transition."""


def _null_sink(result: ReelResult, message: str) -> None:  # pragma: no cover
    pass


def _ydl_opts(base: dict, cookies_from_browser: Optional[str]) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True}
    opts.update(base)
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def fetch_metadata(url: str, cookies_from_browser: Optional[str] = None) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts({"skip_download": True}, cookies_from_browser)) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    return ydl.sanitize_info(info) if hasattr(ydl, "sanitize_info") else info


def _download(url: str, outtmpl: str, fmt: Optional[str],
              cookies_from_browser: Optional[str]) -> Path:
    import yt_dlp
    base = {"outtmpl": outtmpl}
    if fmt:
        base["format"] = fmt
    with yt_dlp.YoutubeDL(_ydl_opts(base, cookies_from_browser)) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        return Path(ydl.prepare_filename(info))


def process_url(
    url: str,
    lib: Library,
    whisper_model: str = "small.en",
    language: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    sink: ProgressSink = _null_sink,
    result: Optional[ReelResult] = None,
) -> ReelResult:
    r = result or ReelResult(url=url)
    r.status = "running"
    try:
        # 1. metadata ------------------------------------------------------
        r.stage = "metadata"
        sink(r, "fetching metadata")
        info = fetch_metadata(url, cookies_from_browser)
        r.video_id = str(info.get("id", ""))
        r.uploader = info.get("uploader") or info.get("channel") or "unknown"
        r.title = (info.get("title") or "").strip()
        r.duration = float(info.get("duration") or 0)

        existing = lib.find_by_video_id(r.video_id) if r.video_id else None
        if existing:
            r.status = "skipped"
            r.error = f"duplicate of existing file: {existing.name}"
            sink(r, r.error)
            return r

        lib.ensure_dirs()
        n = lib.next_number()
        r.number = n
        width = lib.width()
        stem = f"{n:0{width}d}_{safe_component(r.uploader)}_{r.video_id}"
        lib.save_meta(n, info)

        # 2. video ---------------------------------------------------------
        r.stage = "video"
        sink(r, "downloading video")
        vpath = _download(url, str(lib.videos / f"{stem}.%(ext)s"), None,
                          cookies_from_browser)
        r.files["video"] = vpath.name

        # 3. audio ---------------------------------------------------------
        r.stage = "audio"
        sink(r, "downloading audio stream")
        try:
            apath = _download(url, str(lib.audio / f"{stem}.%(ext)s"),
                              "bestaudio", cookies_from_browser)
        except Exception:
            apath = vpath  # some extractors expose no audio-only stream
        r.files["audio"] = apath.name

        # 4. thumbnail -----------------------------------------------------
        r.stage = "thumbnail"
        sink(r, "saving thumbnail")
        thumb_url = info.get("thumbnail")
        if thumb_url:
            tpath = lib.thumbnails / f"{n:0{width}d}.jpg"
            try:
                req = urllib.request.Request(thumb_url,
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    tpath.write_bytes(resp.read())
                r.files["thumbnail"] = tpath.name
            except Exception as e:  # non-fatal
                sink(r, f"thumbnail failed: {e}")

        # 5. transcript ----------------------------------------------------
        r.stage = "transcript"
        sink(r, "transcribing (this loads Whisper on first run)")
        tr_path = lib.transcripts / f"{stem}.txt"
        segments, duration = transcribe.transcribe_file(
            apath, model_name=whisper_model, language=language)
        transcribe.write_transcript(tr_path, segments, duration)
        r.files["transcript"] = tr_path.name
        r.has_speech = bool(segments)
        if r.duration == 0:
            r.duration = duration

        # 6. draft document --------------------------------------------------
        r.stage = "document"
        sink(r, "writing draft doc")
        doc_name = f"{n:0{width}d}_{slugify(docgen.clean_title(info))}_{slugify(r.uploader, 4)}.md"
        doc_path = lib.documents / doc_name
        docgen.write_draft(doc_path, number=n, info=info, files=r.files,
                           segments=segments, has_speech=r.has_speech)
        r.files["document"] = doc_name

        # enrichment record ---------------------------------------------------
        enrich = {
            "number": n, "url": info.get("webpage_url") or url,
            "video_id": r.video_id, "uploader": r.uploader, "title": r.title,
            "duration": r.duration, "has_speech": r.has_speech,
            "files": r.files, "ingested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "enriched": False,
        }
        (lib.enrich_dir / f"{n:0{width}d}.json").write_text(
            json.dumps(enrich, indent=2, ensure_ascii=False), encoding="utf-8")

        r.status = "done"
        sink(r, "done")
    except Exception as e:
        r.status = "error"
        r.error = str(e)
        sink(r, f"error: {e}")
    return r


def process_batch(
    urls: List[str],
    lib: Library,
    whisper_model: str = "small.en",
    language: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    sink: ProgressSink = _null_sink,
    results: Optional[List[ReelResult]] = None,
) -> List[ReelResult]:
    """Sequential batch — deliberate: library numbering must be serial, and
    Whisper keeps one model in memory."""
    out = results if results is not None else [ReelResult(url=u) for u in urls]
    for r in out:
        if r.status == "pending":
            process_url(r.url, lib, whisper_model=whisper_model, language=language,
                        cookies_from_browser=cookies_from_browser, sink=sink, result=r)
    return out
