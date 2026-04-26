"""Audio transcription parser — converts audio files to text markdown.

Uses SpeechRecognition for transcription and optionally pydub + ffmpeg for
format conversion. Native support is strongest for WAV / FLAC / AIFF inputs;
compressed formats rely on ffmpeg being available in the runtime.
"""

from __future__ import annotations

import asyncio
import tempfile
import warnings
from pathlib import Path
from shutil import which

import structlog

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    AudioSegment = None
    PYDUB_AVAILABLE = False


logger = structlog.get_logger()

_NATIVE_AUDIO_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif"}
FFMPEG_BINARY = which("ffmpeg") or which("avconv")
FFMPEG_AVAILABLE = bool(FFMPEG_BINARY)

# We still expose the parser when SpeechRecognition is installed because WAV /
# FLAC / AIFF can run without ffmpeg. Compressed formats are gated per-extension.
AUDIO_NATIVE_AVAILABLE = SPEECH_RECOGNITION_AVAILABLE


def is_audio_transcription_available(extension: str | None = None) -> bool:
    """Return whether audio transcription is runnable for one extension."""

    if not SPEECH_RECOGNITION_AVAILABLE:
        return False
    if extension is None:
        return True
    normalized = extension.lower()
    if normalized in _NATIVE_AUDIO_EXTENSIONS:
        return True
    return PYDUB_AVAILABLE and FFMPEG_AVAILABLE


async def parse_audio_with_transcription(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Transcribe audio file to markdown text."""
    return await asyncio.to_thread(
        _parse_audio_sync, Path(file_path), asset_dir, options
    )


def _parse_audio_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if sr is None:
        raise FileParseError(path.name, reason="SpeechRecognition is not available.")

    logger.info("parse_audio_start", filename=path.name, extension=path.suffix.lower())

    recognizer = sr.Recognizer()

    # Convert non-WAV formats to WAV using pydub
    wav_path = _ensure_wav(path)

    try:
        with sr.AudioFile(str(wav_path)) as source:
            # Get audio duration for logging
            duration_s = source.DURATION
            logger.info("parse_audio_loaded", filename=path.name, duration_s=round(duration_s, 1))

            # For long audio, process in chunks
            if duration_s > 60:
                text = _transcribe_long_audio(recognizer, source, duration_s, path.name)
            else:
                audio_data = recognizer.record(source)
                text = _transcribe_chunk(recognizer, audio_data, path.name)
    finally:
        # Clean up temp WAV if we created one
        if wav_path != path and wav_path.exists():
            try:
                wav_path.unlink()
            except OSError:
                pass

    if not text or not text.strip():
        raise FileParseError(path.name, reason="Audio transcription returned empty text.")

    # Format as markdown
    duration_min = round(duration_s / 60, 1)
    markdown = (
        f"# Audio Transcription: {path.name}\n\n"
        f"> Duration: {duration_min} minutes\n\n"
        f"{text.strip()}\n"
    )

    logger.info(
        "parse_audio_done",
        filename=path.name,
        duration_s=round(duration_s, 1),
        chars=len(markdown),
    )
    return markdown


def _ensure_wav(path: Path) -> Path:
    """Convert audio to WAV format if needed. Returns path to WAV file."""
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return path

    if suffix in _NATIVE_AUDIO_EXTENSIONS:
        return path

    if AudioSegment is None:
        raise FileParseError(
            path.name,
            reason=(
                f"Converting {suffix} to WAV requires pydub and ffmpeg. "
                "Install pydub and ensure ffmpeg is on PATH."
            ),
        )

    if not FFMPEG_AVAILABLE:
        raise FileParseError(
            path.name,
            reason=(
                f"Converting {suffix} to WAV requires ffmpeg or avconv on PATH. "
                "WAV / FLAC / AIFF files can still be parsed directly."
            ),
        )

    logger.debug("audio_converting_to_wav", filename=path.name, format=path.suffix)

    try:
        audio = AudioSegment.from_file(str(path))
        # Convert to mono 16kHz for better recognition
        audio = audio.set_channels(1).set_frame_rate(16000)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio.export(tmp.name, format="wav")
        return Path(tmp.name)
    except Exception as exc:
        raise FileParseError(
            path.name,
            reason=f"Failed to convert audio to WAV: {exc}",
        ) from exc


def _transcribe_long_audio(
    recognizer,
    source,
    duration_s: float,
    filename: str,
) -> str:
    """Transcribe long audio in 30-second chunks."""
    chunks: list[str] = []
    chunk_duration = 30  # seconds
    offset = 0.0

    while offset < duration_s:
        remaining = duration_s - offset
        current_chunk = min(chunk_duration, remaining)

        audio_data = recognizer.record(source, duration=current_chunk)
        chunk_text = _transcribe_chunk(recognizer, audio_data, filename)

        if chunk_text and chunk_text.strip():
            chunks.append(chunk_text.strip())

        offset += current_chunk
        logger.debug(
            "audio_chunk_transcribed",
            filename=filename,
            offset=round(offset, 1),
            total=round(duration_s, 1),
        )

    return "\n\n".join(chunks)


def _transcribe_chunk(recognizer, audio_data, filename: str) -> str:
    """Transcribe a single audio chunk using the best available backend."""
    try:
        # Try Google Speech Recognition (free, no API key)
        text = recognizer.recognize_google(audio_data, language="zh-CN")
        return text
    except sr.UnknownValueError:
        logger.debug("audio_chunk_unrecognized", filename=filename)
        return ""
    except sr.RequestError as exc:
        logger.warning("audio_transcription_api_error", filename=filename, error=str(exc))
        # Try with English as fallback
        try:
            text = recognizer.recognize_google(audio_data, language="en-US")
            return text
        except Exception:
            return "[Audio transcription failed]"
    except Exception as exc:
        logger.warning("audio_transcription_failed", filename=filename, error=str(exc))
        return "[Audio transcription failed]"

