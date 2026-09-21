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
# Caps what one request can cost, since the endpoint will be public once deployed.
MAX_CHARS = 600
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


def synthesize(text: str, voice: str = VOICE_ID, client=None, cache_dir: Path = CACHE_DIR) -> bytes | None:
    text = " ".join(text.split())
    if not text or len(text) > MAX_CHARS:
        return None

    key = hashlib.sha256(f"{voice}|{ENGINE}|ssml-{PAUSE_MS}|{text}".encode()).hexdigest()[:32]
    cached = cache_dir / f"{key}.mp3"
    if cached.exists():
        return cached.read_bytes()

    try:
        response = (client or _polly()).synthesize_speech(
            Engine=ENGINE, VoiceId=voice, OutputFormat="mp3", TextType="ssml", Text=to_ssml(text)
        )
        audio = response["AudioStream"].read()
    except (BotoCoreError, ClientError):
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(audio)
    return audio
