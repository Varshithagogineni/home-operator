# Known limitations and deferred work

Things that are understood but deliberately not done yet, with enough detail to
pick up later. Anything listed here has been reproduced, not guessed at.

---

## 1. Interrupting Ruth stops her at the end of her sentence, not mid-word

**Status:** known, accepted for now. The voice and answering path is frozen;
this is the one thing to revisit afterwards.

**What happens.** Talking over Ruth does stop her and she answers the new
question correctly, but she usually finishes the sentence she was on first. It
feels like a polite pause rather than a real interruption.

**Why, and it is not the stopping.** `stopSpeaking()` is immediate: it pauses the
audio element and cancels any browser speech. The delay is upstream, in
recognition. The browser's `SpeechRecognition` does not report interim results
the instant sound arrives - it waits until it has a partial transcript it
believes in, which in Chrome is commonly several hundred milliseconds to over a
second, and often not until the speaker briefly pauses. Ruth's sentences are
short by design, so she frequently finishes before the first words come back.

Put simply: we are waiting to know *what* was said before reacting to the fact
that *something* was said.

**The fix when we return to it.** Stop on sound, not on words. Take the
microphone stream with `getUserMedia({ audio: { echoCancellation: true,
noiseSuppression: true, autoGainControl: true } })`, run it through an
`AudioWorklet` computing short-window RMS, and call `stopSpeaking()` the moment
energy crosses a threshold for ~100 ms while audio is playing. Recognition keeps
running exactly as it does now and still provides the words; it just stops being
what triggers the interruption. Expected latency around 100-150 ms instead of
500-1500 ms.

Two things to be careful about. Echo cancellation must be on, or Ruth's own
output through the speakers trips the threshold - the existing text-based echo
filter in `soundsLikeRuth` cannot help here, because at that point there are no
words to compare. And the threshold wants calibrating against room noise, most
simply by sampling ambient level for a second when hands-free is switched on.

**Worth saying on camera.** A real Alexa+ device does this in the device's own
audio stack, with hardware echo cancellation and wake-word silicon. A browser tab
is not the right place to reimplement that, which is a fair answer if it comes up.

---

## 2. Amazon Nova 2 Sonic, speech to speech

Built on the `nova-sonic` branch (2026-09-25), not merged. `src/home_operator/sonic.py`
relays browser audio to Nova 2 Sonic over a WebSocket at `/voice`, and Sonic calls
the eight tools on AgentCore. The new Echo Show style page is `/sim/`; the old
text simulator is `/sim/classic.html`. Run with `uv sync --group speech`.

What testing against the live model showed:

- Tool use works. `promptStart` with `toolConfiguration` was accepted, and there
  was no hang or loop across a five-turn repair.
- Sonic does chain calls: told "yes, walk me through it" it started the repair,
  tried to clear the power-off gate and advanced, in one breath, and the opening
  safety warning was never spoken. The relay's Guard now allows one repair move
  per thing the person says. The gate held regardless, because the relay passes
  the transcript of what was actually heard as `said`, not the model's version.
- Steps are spoken word for word when the tool reply carries a `speak` line.
  Asked to repeat a held gate in its own words it paraphrased, so held gates get
  a short fixed line. Every repair reply is checked against what Sonic said, and
  drift is shown on the card.
- About 1.7 to 2.3 s from the end of speech to the first audio, including
  end-of-turn detection and the AgentCore tool call.

Still true: the SDK is Developer Preview, Ruth is not among Sonic's voices, and
SSML pacing is gone.

## 3. The furnace's model number is a series, not one unit

Done, with a caveat worth knowing. The furnace is a real Carrier 58STA and its
data comes from Carrier's owner's manual OM58-132, edition 05/18. But the other
four appliances carry full model numbers, and "58STA" is a series covering
fourteen sizes. The record names the size this household is meant to have
(090-14, the 17-1/2 inch casing, which is why the filter is a definite 16 x 25)
and says where that comes from, but the manual itself is written for the family
and says "representative drawing only, some model may vary" four times.

If it ever matters, buy a real furnace's manual rather than a family one. It does
not matter for the demo, and it is written down here rather than left to be
noticed.

## 4. Account linking for a real Alexa+ add-on

The MCP server is authenticated with Cognito machine to machine, which is right
for one agent talking to its own tools. A published Alexa+ add-on would instead
need OAuth 2.1 with PKCE so each customer's own account links to their own home,
and every tool call would carry that customer's identity rather than a service
identity. The data model already keys on a home, so the shape is there.

---

## 5. The agent could run inside AWS

The agent runs locally and reaches AgentCore Runtime over the internet, which
costs about 370 ms per tool call from a laptop. Hosting it alongside the MCP
runtime would remove most of that. `agentcore add agent --protocol HTTP` on the
same project is the path. Not required for the demo, and it would make recording
harder, so it is deliberately after the video.
