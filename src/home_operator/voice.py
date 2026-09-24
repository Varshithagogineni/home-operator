"""Speak replies with Amazon Polly's generative voice, cached on disk.

If AWS isn't reachable (not logged in, session expired, offline), synthesize()
returns None and the simulator falls back to the browser's own voice, so the
project still runs for anyone without an AWS account.
"""
import hashlib
import re
from html import escape
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

VOICE_ID = "Ruth"
ENGINE = "generative"
REGION = "us-east-1"
# A long reply is spoken in several requests rather than refused. The first cap
# was 600 characters, and a 642-character answer - a recall warning followed by
# the overdue list - silently dropped the voice back to the browser's own for the
# rest of the session. Polly's own limit is 3000 billed characters per request;
# these are lower, to keep one reply cheap and to start the audio sooner.
MAX_CHARS = 3000       # refuse anything longer than this outright
CHUNK_CHARS = 1200     # split at sentence ends, at most this much per request
# A beat between sentences so replies land one thought at a time.
PAUSE_MS = 300
CACHE_DIR = Path(__file__).resolve().parents[2] / "media" / "cache"

_client = None


def _polly():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("polly", region_name=REGION)
    return _client


def to_ssml(text: str) -> str:
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]
    pause = f'<break time="{PAUSE_MS}ms"/> '
    return "<speak>" + pause.join(escape(x, quote=False) for x in sentences) + "</speak>"


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]


def chunk(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split a reply into pieces Polly will accept, breaking between sentences.

    A sentence longer than the limit on its own is passed through rather than
    cut mid-word: better one oversized request than a sentence that stops
    halfway.
    """
    chunks: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def synthesize(text: str, voice: str = VOICE_ID, client=None, cache_dir: Path = CACHE_DIR) -> bytes | None:
    text = " ".join(text.split())
    if not text or len(text) > MAX_CHARS:
        return None

    key = hashlib.sha256(f"{voice}|{ENGINE}|ssml-{PAUSE_MS}|{text}".encode()).hexdigest()[:32]
    cached = cache_dir / f"{key}.mp3"
    if cached.exists():
        return cached.read_bytes()

    polly = client or _polly()
    pieces: list[bytes] = []
    try:
        for piece in chunk(text):
            response = polly.synthesize_speech(
                Engine=ENGINE, VoiceId=voice, OutputFormat="mp3",
                TextType="ssml", Text=to_ssml(piece),
            )
            pieces.append(response["AudioStream"].read())
    except (BotoCoreError, ClientError):
        return None

    # MP3 frames play back as one stream when joined, so several requests make
    # a single reply.
    audio = b"".join(pieces)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(audio)
    return audio
