"""Speech to speech with Amazon Nova 2 Sonic, calling the tools on AgentCore.

The browser streams microphone audio here over a WebSocket. This relay streams
it into Nova 2 Sonic over Bedrock's bidirectional stream, and streams Sonic's
voice back. When Sonic wants a tool, the relay calls it on the MCP server on
AgentCore Runtime, the same eight tools the text agent uses.

    browser mic  --PCM 16 kHz-->  relay  --audioInput-->   Nova 2 Sonic
    browser      <--PCM 24 kHz--  relay  <--audioOutput--  Nova 2 Sonic
                                  relay  <--toolUse------  Nova 2 Sonic
                                  relay  --MCP call----->  AgentCore Runtime

The model still only decides which tool to call. What the text path enforced in
chat.py is enforced here too, in the Guard, rather than left to the prompt:

  * the repair id and step number come from the relay's own record of the last
    tool reply, not from what the model remembers;
  * a safety gate is cleared only by the person's own words - the relay passes
    the transcript of what they actually said, whatever the model put in `said`;
  * a repair cannot start in the same breath as the diagnosis that suggested it;
  * "stop" or "never mind" puts a repair down.

What the relay cannot do is choose Sonic's words: it speaks for itself. Every
step reply therefore carries a `speak` line written here from the manual's text,
the prompt tells Sonic to say it exactly, and the relay compares what Sonic said
with it and flags any drift on screen. The card always shows the manual's words.

bidirectional streaming is not in boto3; it needs aws-sdk-bedrock-runtime,
installed with `uv sync --group speech`.
"""

import asyncio
import base64
import difflib
import json
import re
import time
import uuid
from contextlib import AsyncExitStack
from typing import Awaitable, Callable

from home_operator import auth, chat, mcp_client

MODEL_ID = "amazon.nova-2-sonic-v1:0"
VOICE_ID = "tiffany"
INPUT_RATE = 16000
OUTPUT_RATE = 24000

# Sonic closes a stream after eight minutes. Reconnect a little before, carrying
# the conversation so far, rather than letting it drop mid-sentence.
SESSION_SECONDS = 7 * 60 + 30
HISTORY_TURNS = 12

SYSTEM_PROMPT = """\
You are Home Operator, a voice assistant for the appliances in one home. The
person is standing at the machine, often with their hands full. Everything you
say is heard, never read.

How you sound: warm, calm, and short. Like a friend who has done this before and
is in no rush. One sentence is usually enough; never more than two, and under
twenty-five words. No lists, no exclamation marks, no "great question", no
apologising, no offers of extra help they did not ask for. Say numbers as words
a person would say. They can always ask for more.

Only ever say the words meant for the person. Never say what you are thinking
or doing: no "the user", no "I need to call", no "let me check", never a tool
name, never a field name like speak or instruction. Wrong: "The user wants the
filter, so I will call get appliance." Right: "It takes a sixteen by twenty-five
filter."

The hard rules:
- Every fact about this home's appliances comes from a tool. You know nothing
  about them on your own. Never answer from general knowledge about appliances,
  brands, parts or repairs, and never guess a part number or an interval.
- If a tool reply has a "speak" field, say exactly that text, word for word, and
  nothing else for that turn. It is taken from the manufacturer's manual and a
  person checked it. Do not shorten it, reword it, or add a step.
- If a tool reply has a "say_first" field, say it word for word before anything
  else. It is checked safety wording. Never say an appliance "is recalled" or
  tell someone to stop using it: a recall names model numbers, not serial
  numbers, so this one may or may not be affected. Say it once per conversation.
  If a reply has "recall_already_mentioned", do not bring the recall up again
  unless they ask about it.
- When a tool reply returns several things, say how many and the one that
  matters most. The screen shows the rest, so never read out a list.
- If a reply has a "message" and found is false, say the message and stop.
- A field named "instruction" is for you. Follow it; never say it.
- If a tool finds nothing, say so in one sentence. Do not invent checks, steps
  or fixes of your own.

Repairs go one step at a time. Say the one step, then stop and wait. Never read
ahead, never summarise the remaining steps.

Choosing a tool:
- What an appliance is or which part it takes: get_appliance.
- What needs doing, anything due: get_maintenance_due.
- A complaint or an error code: diagnose_symptom. Then say what is most likely
  and offer to walk them through the fix. Do not start the repair until they
  say yes.
- They say yes to a repair, or ask to be walked through one: start_repair.
- During a repair, "next", "back", "repeat", or telling you the machine is off
  or unplugged: navigate_repair. Use "done" when they say it is off or
  unplugged, and put their exact words in "said".
- They ask for a particular step ("tell me step four", "go back to step two",
  "skip to the final step"): navigate_repair with action "repeat" and step set
  to that number. A safety step cannot be skipped; if the reply says to wait,
  say that.
- They finished a job: log_service. A new appliance: add_appliance. They want a
  technician: prepare_pro_brief.
One tool per turn. Do not look an appliance up with get_appliance before another
tool: every tool takes the appliance as the person said it. If a repair is under way and they ask something else, answer
it with the right tool: their place in the repair is kept.
"""


# -- guard: what the prompt asks for, enforced -----------------------------------


def _clean(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def speak_line(name: str, data: dict | None, held: bool = False) -> str | None:
    """The exact words for a repair reply, built from the manual's own text.

    `held` means a safety gate refused to move. The line is then short and fixed,
    because asked to say the full step again Sonic paraphrased it every time.
    """
    if name == "get_maintenance_due":
        return due_line(data)
    if not isinstance(data, dict) or name not in ("start_repair", "navigate_repair"):
        return None
    if data.get("blocked"):
        return data.get("speak")
    if held and data.get("confirm_prompt"):
        return f"Hold on, safety first. {data['confirm_prompt']}"
    if data.get("finished"):
        return f"{data.get('message', 'That was the last step.')} I've logged it."
    if data.get("started") is False or data.get("active") is False:
        return data.get("message")
    if data.get("started"):
        # Composed in the store: warning, first step and gate, in full sentences.
        return data.get("say_first") or f"First, {data.get('step', '')}"
    step = data.get("step")
    if not step:
        return data.get("message")
    line = f"Step {data.get('step_number')}. {step}"
    if data.get("awaiting_confirmation"):
        line = f"{line} {data.get('confirm_prompt', '')}".strip()
    return line


_COUNT = ["no", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def due_line(data: dict | None) -> str | None:
    """One sentence for "what's due", instead of every item read aloud.

    Asked to say how many and the one that matters most, Sonic read out all
    five overdue jobs. The list is on the screen; the voice says the top one.
    """
    if not isinstance(data, dict) or "overdue" not in data:
        return None
    overdue, upcoming = data.get("overdue") or [], data.get("upcoming") or []
    if not overdue:
        if not upcoming:
            return "Nothing's overdue, and nothing is coming up soon."
        nxt = upcoming[0]
        return f"Nothing's overdue. Next up is the {nxt['nickname'].lower()}: {nxt['task']}, in {nxt['days_until']} days."
    top = overdue[0]
    count = _COUNT[len(overdue)] if len(overdue) < len(_COUNT) else str(len(overdue))
    head = "One thing is overdue:" if len(overdue) == 1 else f"{count} things are overdue. The most overdue is"
    tail = " That one is a job for a technician." if top.get("who") == "dealer" else ""
    return f"{head} the {top['nickname'].lower()}: {top['task']}.{tail}"


def coverage(expected: str, actual: str) -> float:
    """How much of the expected line was said, in order: 1.0 is all of it.

    Extra words around it ("Good.", "Take your time.") are allowed; dropped or
    reworded words from the manual are not, so this measures only the one way.
    """
    want = _clean(expected).split()
    if not want:
        return 1.0
    got = _clean(actual).split()
    matched = sum(b.size for b in difflib.SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks())
    return matched / len(want)


# Below this share of the manual's words, the spoken line is flagged as drifted.
MIN_COVERAGE = 0.85


# Sonic now and then speaks its own reasoning aloud: "the user is asking about
# the filter, so I'll call get appliance". The prompt forbids it, but a prompt is
# a request. Each sentence's text arrives just before its audio, so a sentence
# that reads like narration is caught here and its audio is never played.
NARRATION = re.compile(
    r"\b(get appliance|get maintenance due|diagnose symptom|start repair|navigate repair"
    r"|log service|add appliance|prepare pro brief)\b"
    r"|\bthe user\b"
    r"|\b(call|calling|use|using|invoke|invoking|run|running) (the )?(\w+ ){0,3}(tool|function)\b"
    r"|\btool (call|reply|response|result|results|returned|says|output)\b"
    r"|\b(speak|say first|instruction) field\b"
    r"|\b(ill|i will|i need to|i should|i must|let me|im going to) (call|invoke) (the )?"
    r"(get|diagnose|start|navigate|log|add|prepare)\b"
)


# How speech arrives versus how the manuals are indexed. A recogniser hears
# "UE" as "u e", and the store's keyword match then scores only on "error code",
# which every washer code shares - so it answered with the first one, IE. And
# people say "it smells", while the manuals say "odor".
_SPELLED_CODE = re.compile(r"\b(code|error|showing|shows|says|flashing)\s+((?:[a-z0-9]\s+){1,3}[a-z0-9])\b")
_SMELL = re.compile(r"\b(smells?|smelly|smelling|stinks?|stinky|stench)\b")
_ASKED_CODE = re.compile(r"\b(?:code|showing|shows|says|flashing)\s+([a-z]{1,3}-?[0-9]{0,2}|[0-9][a-z0-9]{1,3})\b")
_FOUND_CODE = re.compile(r"code\s+(\S+)$", re.I)


def normalize_symptom(text: str) -> str:
    """A symptom as heard, in the words the manuals were indexed by."""
    t = (text or "").lower()
    t = _SPELLED_CODE.sub(lambda m: f"{m.group(1)} {re.sub(r'\s+', '', m.group(2))}", t)
    return _SMELL.sub("odor", t)


def wrong_code(asked_symptom: str, data: dict | None) -> str | None:
    """The code someone asked about, when the match found a different one."""
    if not isinstance(data, dict) or not data.get("found"):
        return None
    asked = _ASKED_CODE.search(normalize_symptom(asked_symptom))
    found = _FOUND_CODE.search(data.get("symptom") or "")
    if not asked or not found:
        return None
    want, got = asked.group(1).replace("-", ""), found.group(1).lower().replace("-", "")
    return want if len(want) >= 2 and want != got else None


def is_narration(text: str) -> bool:
    return bool(NARRATION.search(_clean(text)))


_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_STEP_NUMBER = re.compile(r"\bstep (?:number )?(\d+|" + "|".join(_NUMBERS) + r")\b")
_STEP_ORDINAL = re.compile(r"\b(" + "|".join(_ORDINALS) + r"|final) step\b")


def requested_step(said: str, total: int | None) -> int | None:
    """The step number someone asked for by name, if they did.

    "Last step" is deliberately not here: in chat.py it already means the step
    before this one, and someone saying it mid-repair usually means that.
    """
    text = _clean(said)
    match = _STEP_NUMBER.search(text)
    if match:
        word = match.group(1)
        return int(word) if word.isdigit() else _NUMBERS[word]
    match = _STEP_ORDINAL.search(text)
    if match:
        return total if match.group(1) == "final" else _ORDINALS[match.group(1)]
    return None


async def walk(call, repair: str, current: int, target: int, total: int) -> tuple[dict | None, bool]:
    """Go to a step by name, without skipping a safety gate.

    Going back is one "repeat" at that step: the server re-asks any gate there.
    Going forward is one "next" at a time, so the server holds at any power-off
    step on the way exactly as it would if the person said "next" themselves.
    Nothing is said on their behalf: `said` is empty, so no gate can clear.
    Returns the reply and whether a gate held the walk short of the target.
    """
    if target <= current:
        return await call("navigate_repair", {"action": "repeat", "repair": repair, "step": target, "said": ""}), False
    step, data = current, None
    while step < target:
        data = await call("navigate_repair", {"action": "next", "repair": repair, "step": step, "said": ""})
        if not isinstance(data, dict) or not data.get("active") or data.get("finished"):
            return data, False
        if data.get("step_number") == step:
            return data, True
        step = data["step_number"]
    return data, False


class Guard:
    """The rules from chat.py, applied to Sonic's tool calls."""

    def __init__(self) -> None:
        self.repair: str | None = None
        self.step: int | None = None
        self.total: int | None = None
        self.last_heard = ""
        self.last_speak: str | None = None
        self.diagnosed_this_turn = False
        self.moved_this_turn = False
        self.warned: set[str] = set()

    def heard(self, text: str) -> None:
        """A new thing the person said: it starts a new turn."""
        self.last_heard = text.strip()
        self.diagnosed_this_turn = False
        self.moved_this_turn = False
        if self.repair and chat.is_escape(self.last_heard):
            self.repair = self.step = self.total = None

    def prepare(self, name: str, args: dict) -> tuple[dict, dict | None]:
        """The arguments to actually send, or a reply that stops the call."""
        args = dict(args or {})
        if name == "start_repair" and self.diagnosed_this_turn:
            return args, {
                "blocked": True,
                "instruction": (
                    "Not started. Tell them what is most likely and offer to walk "
                    "them through the fix, then wait for them to say yes."
                ),
            }
        # One move through a repair per thing the person says. Told "yes, walk
        # me through it", Sonic started the repair, cleared the gate and asked
        # for the next step in one breath, and the opening safety warning was
        # never spoken. The person has to hear a step before moving past it.
        if name in ("start_repair", "navigate_repair") and self.moved_this_turn:
            return args, {
                "blocked": True,
                "speak": self.last_speak,
                "instruction": (
                    "Not moved. Say the speak line and wait for the person to answer. "
                    "Only what they say next can move the repair on."
                ),
            }
        if name == "diagnose_symptom" and args.get("symptom"):
            args["symptom"] = normalize_symptom(args["symptom"])
        if name == "navigate_repair":
            if self.repair:
                args["repair"] = self.repair
                args["step"] = self.step or 1
            # Only the person's own words clear a safety gate. The model's version
            # of what they said is replaced by what was actually heard.
            args["said"] = self.last_heard
            action = chat.fast_action(self.last_heard)
            if action and args.get("action") not in ("next", "back", "repeat", "done"):
                args["action"] = action
        return args, None

    def once(self, name: str, data: dict | None) -> dict | None:
        """The reply for the model, with a recall warning it has already given removed.

        Every look at the dishwasher, and every "what's due", carries the same
        recall warning, and Sonic read it out every time: ask about anything and
        hear about a power cord first. It is said once per conversation, and the
        card keeps showing it. A repair's opening line is not a warning to
        deduplicate - it is the first step - so start_repair is left alone.
        """
        if not isinstance(data, dict) or name == "start_repair" or not data.get("say_first"):
            return data
        if data["say_first"] in self.warned:
            data = {k: v for k, v in data.items() if k != "say_first"}
            data["recall_already_mentioned"] = True
            return data
        self.warned.add(data["say_first"])
        return data

    def jump_target(self, name: str, args: dict) -> int | None:
        """The step to go to, when someone asked for one by number.

        Their own words win; failing that, a "repeat" the model aimed at a
        different step is taken as the jump the prompt tells it to make.
        """
        if name != "navigate_repair" or not self.repair or not self.step:
            return None
        target = requested_step(self.last_heard, self.total)
        if target is None and (args or {}).get("action") == "repeat":
            step = (args or {}).get("step")
            target = step if isinstance(step, int) else None
        return target if target is not None and target != self.step else None

    def observe(self, name: str, data: dict | None, held: bool | None = None) -> bool:
        """Record a tool reply. Returns whether a safety gate held the step still."""
        if name == "diagnose_symptom":
            self.diagnosed_this_turn = True
        if not isinstance(data, dict) or data.get("blocked"):
            return False
        held = held if held is not None else (
            name == "navigate_repair"
            and bool(data.get("awaiting_confirmation"))
            and data.get("step_number") == self.step
            and chat.fast_action(self.last_heard) not in ("repeat", "back")
        )
        if name in ("start_repair", "navigate_repair"):
            self.moved_this_turn = True
        self._track(data)
        return held

    def _track(self, data: dict) -> None:
        if data.get("finished"):
            self.repair = self.step = self.total = None
            return
        if data.get("repair") and (data.get("started") or data.get("active")):
            self.repair = data["repair"]
        if isinstance(data.get("step_number"), int) and self.repair:
            self.step = data["step_number"]
        if isinstance(data.get("total_steps"), int):
            self.total = data["total_steps"]


# -- the Bedrock bidirectional stream --------------------------------------------


def _bedrock_client(region: str):
    """A client for the bidirectional stream, signed with the same credentials
    boto3 would use - including `aws login` sessions, which the preview SDK's own
    resolvers do not read."""
    import boto3
    from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
    from aws_sdk_bedrock_runtime.config import Config
    from smithy_aws_core.identity import AWSCredentialsIdentity
    from smithy_core.aio.interfaces.identity import IdentityResolver

    session = boto3.Session(region_name=region)

    class Boto3Credentials(IdentityResolver):
        async def get_identity(self, *, properties):
            creds = session.get_credentials()
            if creds is None:
                raise RuntimeError("No AWS credentials. Run `aws login`.")
            frozen = creds.get_frozen_credentials()
            return AWSCredentialsIdentity(
                access_key_id=frozen.access_key,
                secret_access_key=frozen.secret_key,
                session_token=frozen.token,
            )

    return BedrockRuntimeClient(
        config=Config(
            endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
            region=region,
            aws_credentials_identity_resolver=Boto3Credentials(),
        )
    )


Emit = Callable[[dict], Awaitable[None]]


class SonicSession:
    """One spoken conversation: a Sonic stream plus an open MCP session.

    `emit` receives everything the browser needs, as small dicts:
      {"type": "audio", "pcm": <base64 16-bit 24 kHz mono>}
      {"type": "transcript", "role": "user"|"assistant", "text": ...}
      {"type": "tool", "name", "args", "data", "ms", "speak"}
      {"type": "drift", "expected", "said", "score"}
      {"type": "interrupted"} / {"type": "turn_end"} / {"type": "error", ...}
    """

    def __init__(self, emit: Emit, voice: str = VOICE_ID) -> None:
        self.emit = emit
        self.voice = voice
        self.guard = Guard()
        self.history: list[tuple[str, str]] = []  # (role, text), finals only
        self._stack = AsyncExitStack()
        self._mcp = None
        self._tools: list[dict] = []
        self._stream = None
        self._reader: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._prompt = ""
        self._audio_content = ""
        self._opened_at = 0.0
        self._closed = False
        self._expected_speak: str | None = None
        self._said: list[str] = []
        self._mute_next = False   # the next audio block speaks narration: drop it
        self._muting = False
        self._role = None
        self._stage = None
        self._pending: set[asyncio.Task] = set()

    # -- lifecycle

    async def start(self) -> None:
        self._mcp = await self._stack.enter_async_context(mcp_client.session())
        self._tools = [
            {"toolSpec": {
                "name": t.name,
                "description": t.description or t.name,
                "inputSchema": {"json": json.dumps(t.input_schema)},
            }}
            for t in (await self._mcp.list_tools()).tools
        ]
        await self._open_stream()

    async def close(self) -> None:
        self._closed = True
        await self._end_stream()
        for task in list(self._pending):
            task.cancel()
        await self._stack.aclose()

    async def _open_stream(self) -> None:
        from aws_sdk_bedrock_runtime.client import InvokeModelWithBidirectionalStreamOperationInput

        region = auth.load_env().get("AWS_REGION", "us-east-1")
        client = _bedrock_client(region)
        self._stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID)
        )
        self._opened_at = time.monotonic()
        self._prompt = str(uuid.uuid4())
        await self._send({"sessionStart": {
            "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.3},
        }})
        await self._send({"promptStart": {
            "promptName": self._prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm", "sampleRateHertz": OUTPUT_RATE,
                "sampleSizeBits": 16, "channelCount": 1, "voiceId": self.voice,
                "encoding": "base64", "audioType": "SPEECH",
            },
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
            "toolConfiguration": {"tools": self._tools},
        }})
        await self._text("SYSTEM", SYSTEM_PROMPT + self._state_note())
        for role, text in self.history[-HISTORY_TURNS:]:
            await self._text(role, text)
        self._audio_content = str(uuid.uuid4())
        await self._send({"contentStart": {
            "promptName": self._prompt, "contentName": self._audio_content,
            "type": "AUDIO", "interactive": True, "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm", "sampleRateHertz": INPUT_RATE,
                "sampleSizeBits": 16, "channelCount": 1,
                "audioType": "SPEECH", "encoding": "base64",
            },
        }})
        self._reader = asyncio.create_task(self._read())

    def _state_note(self) -> str:
        if not self.guard.repair:
            return ""
        return (f"\nA repair is under way: repair id {self.guard.repair}, "
                f"step {self.guard.step}. Keep using navigate_repair for it.")

    async def _end_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            await self._send_on(stream, {"contentEnd": {"promptName": self._prompt, "contentName": self._audio_content}})
            await self._send_on(stream, {"promptEnd": {"promptName": self._prompt}})
            await self._send_on(stream, {"sessionEnd": {}})
            await stream.input_stream.close()
        except Exception:  # noqa: BLE001 - closing must not raise
            pass
        # Let the reader drain to the end of the stream. Cancelling it mid-read
        # leaves the CRT transport writing into a cancelled future.
        reader = self._reader
        if reader and reader is not asyncio.current_task():
            try:
                await asyncio.wait_for(reader, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _renew(self) -> None:
        """Swap to a fresh stream before Sonic's eight-minute limit."""
        await self._end_stream()
        if not self._closed:
            await self._open_stream()

    # -- sending

    async def _send_on(self, stream, event: dict) -> None:
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalInputPayloadPart,
            InvokeModelWithBidirectionalStreamInputChunk,
        )
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=json.dumps({"event": event}).encode())
        )
        async with self._send_lock:
            await stream.input_stream.send(chunk)

    async def _send(self, event: dict) -> None:
        if self._stream is not None:
            await self._send_on(self._stream, event)

    async def _text(self, role: str, text: str) -> None:
        name = str(uuid.uuid4())
        await self._send({"contentStart": {
            "promptName": self._prompt, "contentName": name, "type": "TEXT",
            "interactive": False, "role": role,
            "textInputConfiguration": {"mediaType": "text/plain"},
        }})
        await self._send({"textInput": {"promptName": self._prompt, "contentName": name, "content": text}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": name}})

    async def send_audio(self, pcm16: bytes) -> None:
        """16-bit little-endian mono PCM at 16 kHz, straight from the microphone."""
        if self._closed:
            return
        if self._stream is None or time.monotonic() - self._opened_at > SESSION_SECONDS:
            await self._renew()
        await self._send({"audioInput": {
            "promptName": self._prompt, "contentName": self._audio_content,
            "content": base64.b64encode(pcm16).decode(),
        }})

    # -- receiving

    async def _read(self) -> None:
        stream = self._stream
        try:
            _, output = await stream.await_output()
            while True:
                event = await output.receive()
                if event is None:
                    break
                payload = getattr(getattr(event, "value", None), "bytes_", None)
                if not payload:
                    continue
                await self._handle(json.loads(payload).get("event", {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the browser
            if stream is self._stream and not self._closed:
                await self.emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
                self._stream = None  # the next audio frame reopens it

    async def _handle(self, ev: dict) -> None:
        if "contentStart" in ev:
            start = ev["contentStart"]
            self._role = start.get("role")
            fields = start.get("additionalModelFields")
            self._stage = json.loads(fields).get("generationStage") if fields else None
            if start.get("type") == "AUDIO":
                # This audio speaks the sentence whose text just arrived.
                self._muting, self._mute_next = self._mute_next, False
        elif "textOutput" in ev:
            await self._on_text(ev["textOutput"])
        elif "audioOutput" in ev:
            if not self._muting:
                await self.emit({"type": "audio", "pcm": ev["audioOutput"]["content"]})
        elif "toolUse" in ev:
            use = ev["toolUse"]
            task = asyncio.create_task(self._tool(use))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        elif "userSpeechStart" in ev:
            await self.emit({"type": "listening"})
        elif "userSpeechEnd" in ev:
            await self.emit({"type": "thinking"})
        elif "contentEnd" in ev:
            reason = ev["contentEnd"].get("stopReason")
            if ev["contentEnd"].get("type") == "AUDIO":
                self._muting = False
            if reason == "INTERRUPTED":
                await self.emit({"type": "interrupted"})
            elif reason == "END_TURN":
                await self.emit({"type": "turn_end"})
        elif "completionEnd" in ev:
            await self.emit({"type": "turn_end"})

    async def _on_text(self, out: dict) -> None:
        text = out.get("content", "")
        role = (out.get("role") or self._role or "").upper()
        if text.strip().startswith("{") and '"interrupted"' in text:
            await self.emit({"type": "interrupted"})
            return
        if role == "USER":
            await self._check_spoken()
            self.guard.heard(text)
            self.history.append(("USER", text))
            await self.emit({"type": "transcript", "role": "user", "text": text})
        elif role == "ASSISTANT" and self._stage == "SPECULATIVE":
            # Arrives a sentence ahead of its audio: good for captions, but it
            # can still change, so it is never recorded or checked.
            if is_narration(text):
                self._mute_next = True
                await self.emit({"type": "narration_muted", "text": text.strip()})
                return
            await self.emit({"type": "caption", "text": text})
        elif role == "ASSISTANT":
            text = text.strip()
            if is_narration(text):
                return
            self._said.append(text)
            if self.history and self.history[-1][0] == "ASSISTANT":
                self.history[-1] = ("ASSISTANT", f"{self.history[-1][1]} {text}")
            else:
                self.history.append(("ASSISTANT", text))
            await self.emit({"type": "transcript", "role": "assistant", "text": text})

    async def _check_spoken(self) -> None:
        """Compare what Sonic said after a repair reply with what it was told to say."""
        expected, said = self._expected_speak, " ".join(self._said)
        self._expected_speak, self._said = None, []
        if not expected or not said:
            return
        share = coverage(expected, said)
        await self.emit({"type": "fidelity", "expected": expected, "said": said,
                         "coverage": round(share, 2), "ok": share >= MIN_COVERAGE})

    async def _tool(self, use: dict) -> None:
        name = use.get("toolName", "")
        try:
            args = json.loads(use.get("content") or "{}")
        except ValueError:
            args = {}
        asked = dict(args)
        call_id = use.get("toolUseId", "")
        await self.emit({"type": "tool_start", "id": call_id, "name": name, "args": asked})
        args, blocked = self.guard.prepare(name, args)
        target = None if blocked else self.guard.jump_target(name, asked)
        started = time.perf_counter()
        calls, held = 1, None
        if blocked is not None:
            data, calls = blocked, 0
        elif target is not None and self.guard.total and not 1 <= target <= self.guard.total:
            data, calls = {"blocked": True, "instruction": (
                f"There are only {self.guard.total} steps. Say so in one short sentence."
            )}, 0
        else:
            try:
                if target is not None:
                    counter = {"n": 0}

                    async def call(tool, arguments):
                        counter["n"] += 1
                        return chat._first_json(await self._mcp.call_tool(tool, arguments))

                    frm = self.guard.step
                    data, held = await walk(call, self.guard.repair, frm, target, self.guard.total or target)
                    calls = counter["n"]
                    args = {"action": "go to step", "repair": self.guard.repair, "from": frm, "to": target}
                else:
                    data = chat._first_json(await self._mcp.call_tool(name, args))
                    code = wrong_code(args.get("symptom", ""), data) if name == "diagnose_symptom" else None
                    if code:
                        data = {"found": False, "nickname": data.get("nickname"), "room": data.get("room"),
                                "message": f"There's no error code {code.upper()} for the {data.get('nickname', 'appliance').lower()} in its manual.",
                                "instruction": "Say that one sentence. Do not describe any other code."}
            except Exception as exc:  # noqa: BLE001 - the model is told, and says so
                data = {"error": f"The tool failed: {type(exc).__name__}. Say you could not reach it."}
        ms = round((time.perf_counter() - started) * 1000)
        held = self.guard.observe(name, data, held)
        speak = speak_line(name, data, held)
        if held and target is not None and isinstance(data, dict) and data.get("confirm_prompt"):
            speak = f"We can't skip past this one. {data['confirm_prompt']}"
        spoken = self.guard.once(name, data)
        reply = dict(spoken) if isinstance(spoken, dict) else {"result": data}
        await self._check_spoken()  # anything said before this call is not this line
        if speak:
            reply["speak"] = speak
            self._expected_speak = speak
            self.guard.last_speak = speak
        await self.emit({"type": "tool", "id": call_id, "name": name, "asked": asked, "args": args,
                         "data": data, "ms": ms, "calls": calls, "speak": speak, "held": held,
                         "blocked": bool(blocked) or bool(isinstance(data, dict) and data.get("blocked")),
                         "reason": (data or {}).get("instruction") if isinstance(data, dict) else None})
        await self._tool_result(use["toolUseId"], reply)

    async def _tool_result(self, tool_use_id: str, reply: dict) -> None:
        name = str(uuid.uuid4())
        await self._send({"contentStart": {
            "promptName": self._prompt, "contentName": name, "interactive": False,
            "type": "TOOL", "role": "TOOL",
            "toolResultInputConfiguration": {
                "toolUseId": tool_use_id, "type": "TEXT",
                "textInputConfiguration": {"mediaType": "text/plain"},
            },
        }})
        await self._send({"toolResult": {"promptName": self._prompt, "contentName": name, "content": json.dumps(reply)}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": name}})
