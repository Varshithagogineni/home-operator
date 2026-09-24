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


# --- Long replies -------------------------------------------------------------
#
# A 642-character answer - a recall warning followed by the overdue list - was
# refused outright by a 600-character cap. The browser quietly fell back to its
# own voice and stayed there, so every later reply came out in a different voice.

def test_a_long_reply_is_split_rather_than_refused():
    from home_operator import voice

    text = " ".join(f"This is sentence number {i}." for i in range(120))
    assert len(text) > voice.CHUNK_CHARS
    pieces = voice.chunk(text)
    assert len(pieces) > 1
    assert all(len(p) <= voice.CHUNK_CHARS for p in pieces)
    assert " ".join(pieces) == text, "no words are lost in the split"


def test_the_reply_that_broke_it_now_survives():
    from home_operator import voice

    text = (
        "Before anything else, heads up. Your dishwasher's model is named in a safety "
        "recall, so it may be affected. The dishwasher power cord can overheat and catch "
        "fire. Check the serial number against the notice. If yours is included, the fix "
        "is free. Otherwise, three things are overdue. The washer's water hoses are almost "
        "three years past due. The furnace filter is twenty-five days overdue. The washer "
        "door seal is twenty-four days overdue. The fridge filter is eight days overdue. "
        "The washer also needs its detergent dispenser cleaned today, and the tub clean "
        "cycle is due in eleven days. The furnace tune-up is due in twenty-six days."
    )
    assert len(text) > 600
    assert len(text) <= voice.MAX_CHARS
    assert voice.chunk(text), "it should be speakable, not refused"


def test_a_single_huge_sentence_is_not_cut_in_half():
    from home_operator import voice

    sentence = "word " * 400 + "end."
    pieces = voice.chunk(sentence)
    assert pieces == [sentence.strip()]


def test_several_chunks_come_back_as_one_recording(tmp_path):
    from home_operator import voice

    class FakePolly:
        def __init__(self):
            self.calls = 0

        def synthesize_speech(self, **kwargs):
            self.calls += 1
            return {"AudioStream": _Stream(f"part{self.calls}".encode())}

    class _Stream:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

    polly = FakePolly()
    text = " ".join(f"Sentence number {i} goes here." for i in range(100))
    audio = voice.synthesize(text, client=polly, cache_dir=tmp_path)

    assert polly.calls > 1, "a long reply needs more than one request"
    assert audio == b"".join(f"part{i}".encode() for i in range(1, polly.calls + 1))
