"""faster-whisper transcription with a cached model instance."""

from __future__ import annotations

from pathlib import Path

_model = None
_model_name = None


def get_model(name: str = "small.en"):
    global _model, _model_name
    if _model is None or _model_name != name:
        from faster_whisper import WhisperModel
        _model = WhisperModel(name, device="cpu", compute_type="int8")
        _model_name = name
    return _model


def transcribe_file(
    audio_path: Path,
    model_name: str = "small.en",
    language: str | None = None,
) -> tuple[list[dict], float]:
    """Returns ([{start, end, text}, ...], duration_seconds).

    Empty segment list ⇒ no speech detected (music-only / silent reel).
    """
    model = get_model(model_name)
    kwargs = {"beam_size": 5, "vad_filter": True}
    if language:
        kwargs["language"] = language
    segments, info = model.transcribe(str(audio_path), **kwargs)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
    return out, float(info.duration)


def write_transcript(path: Path, segments: list[dict], duration: float) -> None:
    """Same on-disk format as the manual pipeline this tool replaces."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Duration: {duration:.1f}s\n\n")
        for seg in segments:
            fh.write(f"[{seg['start']:6.2f}s-{seg['end']:6.2f}s]{seg['text']}\n")
