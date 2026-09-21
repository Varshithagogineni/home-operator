import io

from botocore.exceptions import ClientError, NoCredentialsError
from starlette.testclient import TestClient

from home_operator import server, voice


class FakePolly:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def synthesize_speech(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"AudioStream": io.BytesIO(b"ID3-fake-mp3")}


def test_uses_ruth_generative_mp3(tmp_path):
    polly = FakePolly()
    assert voice.synthesize("Hello there.", client=polly, cache_dir=tmp_path) == b"ID3-fake-mp3"
    assert polly.calls[0] == {"Engine": "generative", "VoiceId": "Ruth", "OutputFormat": "mp3",
                              "TextType": "ssml", "Text": "<speak>Hello there.</speak>"}


def test_sentences_get_a_pause_and_markup_is_escaped():
    ssml = voice.to_ssml("Ah, standing water. That's the filter & the pump? Maybe <not>!")
    assert ssml == ('<speak>Ah, standing water.<break time="300ms"/> '
                    'That\'s the filter &amp; the pump?<break time="300ms"/> Maybe &lt;not&gt;!</speak>')


def test_repeat_lines_come_from_the_cache_without_another_call(tmp_path):
    polly = FakePolly()
    voice.synthesize("Step two.", client=polly, cache_dir=tmp_path)
    voice.synthesize("  Step   two. ", client=polly, cache_dir=tmp_path)
    assert len(polly.calls) == 1


def test_overlong_or_empty_text_is_refused_without_calling_aws(tmp_path):
    polly = FakePolly()
    assert voice.synthesize("x" * (voice.MAX_CHARS + 1), client=polly, cache_dir=tmp_path) is None
    assert voice.synthesize("   ", client=polly, cache_dir=tmp_path) is None
    assert polly.calls == []


def test_aws_failures_return_none_so_the_browser_voice_takes_over(tmp_path):
    for error in (NoCredentialsError(), ClientError({"Error": {"Code": "Throttling", "Message": "slow down"}}, "SynthesizeSpeech")):
        assert voice.synthesize("Hello.", client=FakePolly(error=error), cache_dir=tmp_path) is None
    assert not any(tmp_path.iterdir())


def test_speak_endpoint_returns_audio_or_503(monkeypatch):
    client = TestClient(server.build_app())

    monkeypatch.setattr(voice, "synthesize", lambda text: b"ID3-audio")
    ok = client.post("/speak", json={"text": "Hello."})
    assert ok.status_code == 200 and ok.headers["content-type"] == "audio/mpeg"

    monkeypatch.setattr(voice, "synthesize", lambda text: None)
    assert client.post("/speak", json={"text": "Hello."}).status_code == 503
