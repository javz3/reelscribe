"""Library layout adapter.

A *library* is a folder with this structure (created on demand):

    <root>/
        Videos/
            NNN_<Uploader>_<video_id>.mp4        downloaded videos
            Audio/
                NNN_<Uploader>_<video_id>.m4a    audio-only streams
                Transcripts/
                    NNN_<Uploader>_<video_id>.txt
            Thumbnails/
                NNN.jpg
            Document/
                NNN_<slug>_<creator-slug>.md     one doc per reel
        .reelscribe/
            meta/NNN.json                        raw yt-dlp metadata
            enrich/                              enrichment bundles

Numbering continues from the highest NNN found in Videos/ (video files are
the source of truth for numbering, falling back to Document/).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Optional

NUM_RE = re.compile(r"^(\d{2,4})_")
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)

    # -- paths -------------------------------------------------------------
    @property
    def videos(self) -> Path:
        return self.root / "Videos"

    @property
    def audio(self) -> Path:
        return self.videos / "Audio"

    @property
    def transcripts(self) -> Path:
        return self.audio / "Transcripts"

    @property
    def thumbnails(self) -> Path:
        return self.videos / "Thumbnails"

    @property
    def documents(self) -> Path:
        return self.videos / "Document"

    @property
    def state_dir(self) -> Path:
        return self.root / ".reelscribe"

    @property
    def meta_dir(self) -> Path:
        return self.state_dir / "meta"

    @property
    def enrich_dir(self) -> Path:
        return self.state_dir / "enrich"

    @property
    def readme(self) -> Path:
        return self.root / "README.md"

    def ensure_dirs(self) -> None:
        for p in (self.videos, self.audio, self.transcripts, self.thumbnails,
                  self.documents, self.meta_dir, self.enrich_dir):
            p.mkdir(parents=True, exist_ok=True)

    # -- numbering & dedup ---------------------------------------------------
    def _numbers_in(self, folder: Path, exts: Optional[set] = None) -> List[int]:
        if not folder.is_dir():
            return []
        nums = []
        for f in folder.iterdir():
            if exts and f.suffix.lower() not in exts:
                continue
            m = NUM_RE.match(f.name)
            if m:
                nums.append(int(m.group(1)))
        return nums

    def next_number(self) -> int:
        nums = self._numbers_in(self.videos, VIDEO_EXTS) or self._numbers_in(self.documents)
        return (max(nums) + 1) if nums else 1

    def width(self) -> int:
        """Zero-pad width, inferred from existing files (default 3)."""
        if self.videos.is_dir():
            for f in sorted(self.videos.iterdir()):
                m = NUM_RE.match(f.name)
                if m:
                    return max(len(m.group(1)), 2)
        return 3

    def find_by_video_id(self, video_id: str) -> Optional[Path]:
        """Return an existing video file whose name embeds this platform video id."""
        if not self.videos.is_dir():
            return None
        needle = f"_{video_id}."
        for f in self.videos.iterdir():
            if f.is_file() and needle in f.name:
                return f
        return None

    # -- stats ---------------------------------------------------------------
    def stats(self) -> dict:
        count = lambda folder, exts=None: len(  # noqa: E731
            [f for f in folder.iterdir()
             if f.is_file() and (not exts or f.suffix.lower() in exts)]
        ) if folder.is_dir() else 0
        return {
            "root": str(self.root),
            "videos": count(self.videos, VIDEO_EXTS),
            "audio": count(self.audio, {".m4a", ".mp3", ".opus", ".webm"}),
            "transcripts": count(self.transcripts, {".txt"}),
            "documents": count(self.documents, {".md"}),
            "thumbnails": count(self.thumbnails, {".jpg", ".png", ".webp"}),
            "next_number": self.next_number(),
        }

    # -- README taxonomy -------------------------------------------------------
    def categories(self) -> List[str]:
        """Parse '## Section' headings out of the library README (the taxonomy)."""
        if not self.readme.exists():
            return []
        skip = {"sub-libraries", "quick navigation by topic", "library stats",
                "suggested decision flow", "created / updated"}
        cats = []
        for line in self.readme.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                title = line[3:].strip()
                if title.lower() not in skip:
                    cats.append(title)
        return cats

    def save_meta(self, number: int, info: dict) -> Path:
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        p = self.meta_dir / f"{number:0{self.width()}d}.json"
        p.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        return p


# -- filename helpers ----------------------------------------------------------
def safe_component(text: str, max_len: int = 60) -> str:
    """Uploader name → filesystem-safe path component (spaces preserved,
    matching the existing library convention)."""
    text = unicodedata.normalize("NFKC", text or "unknown")
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip()
    return (text or "unknown")[:max_len]


def slugify(text: str, max_words: int = 7) -> str:
    """Title → short_snake_case_slug for document filenames."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    stop = {"a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
            "with", "your", "you", "this", "that", "is", "are", "it", "its"}
    kept = [w for w in words if w not in stop][:max_words]
    return "_".join(kept) or "untitled"


def extract_urls(text: str) -> List[str]:
    """Pull http(s) URLs out of arbitrary text (batch files, markdown lists)."""
    urls = re.findall(r"https?://[^\s\)\]\">,]+", text)
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def dedupe(urls: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
