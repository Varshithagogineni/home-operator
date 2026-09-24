"""The layer between the browser and the agent.

One conversation per browser session, because both expensive things want to be
reused: the Strands agent (which holds the conversation history) and the MCP
session to AgentCore Runtime (whose first handshake takes about five seconds).

Two paths through here, and the split is the point:

  fast path   "next", "back", "repeat", "it's unplugged"
              -> straight to navigate_repair, no model, no reasoning.
              Someone standing at a machine with wet hands should not wait for a
              language model to decide that "next" means next.

  agent path  everything else
              -> Bedrock picks the tool, then speaks.

Both paths call the same tools on AgentCore Runtime, so the fast path is not a
local shortcut that skips the real system: it skips only the model.
"""

import asyncio
import json
import re
import threading
import time

from strands import Agent

from home_operator import agent as ha
from home_operator import mcp_client

# Phrases that can only mean "move through the repair". The whole utterance has
# to be one of these: matching a prefix would send "next week I'll replace the
# hoses" and "done with the laundry, what about the oven" down the fast path,
# where they would be read as navigation and the real question would be lost.
FAST_ACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(next( step)?|continue|go on|carry on|got it|done with that)"), "next"),
    (re.compile(r"(back|go back|previous( step)?|last step|back a step|one step back)"), "back"),
    (re.compile(r"(repeat( that)?|again|say that again|what was that|one more time|come again)"), "repeat"),
    (re.compile(r"(done|confirmed|confirm|off|its off|it is off|unplugged|its unplugged|it is unplugged|power is off|i unplugged it|all set)"), "done"),
]

# Politeness that does not change the meaning of a command.
# "now" is deliberately not stripped here: "not now" means something.
TRAILING = re.compile(r"\s+(please|then|thanks|thank you)$")
LEADING = re.compile(r"^(ok|okay|alright|right|and|so|um|uh|yeah|yep)[,\s]+")


# Agreeing to an offered repair. Kept separate from the navigation words: this
# starts a repair rather than moving through one.
ACCEPTANCES = re.compile(
    r"(yes|yes please|yeah|yep|sure|ok|okay|please|please do|go ahead|do it|lets do it|"
    r"walk me through it|walk me through that|show me|talk me through it|"
    r"yes walk me through it|i guess|why not)"
)


def is_acceptance(said: str) -> bool:
    """Whether this is someone saying yes to a repair that was just offered."""
    return bool(ACCEPTANCES.fullmatch(_clean(said)))


# Leaving a repair. Without this the only way out of a safety gate is to say the
# machine is off, which is a trap: someone who changed their mind, or who came
# back to ask something else, was told the same sentence forever.
ESCAPES = re.compile(
    r"(stop|cancel|quit|exit|never mind|nevermind|forget it|leave it|leave that|"
    r"start over|start again|not now|later|abandon|stop the repair|im done with this)"
)


def _clean(said: str) -> str:
    """A spoken phrase reduced to its words, for exact matching.

    Punctuation has to go, not just the punctuation at the end: "Yes, walk me
    through it" failed to match "yes walk me through it" because of the comma,
    so the suggestion chip of that exact wording fell through to the model and
    no repair started.
    """
    # Apostrophes close up ("it's" -> "its"); everything else becomes a space,
    # so a comma separates words rather than welding them together.
    text = said.lower().replace("'", "").replace("\u2019", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = LEADING.sub("", text)
    return TRAILING.sub("", text).strip()


def is_escape(said: str) -> bool:
    """Whether someone wants out of the repair they are in."""
    return bool(ESCAPES.fullmatch(_clean(said)))


def fast_action(said: str) -> str | None:
    """The navigation action a phrase means, or None to let the model decide.

    Deliberately conservative: anything that could mean something else goes to
    the model. Sending a real question down the fast path would answer the wrong
    thing, which is worse than being slow.
    """
    text = _clean(said)
    for pattern, action in FAST_ACTIONS:
        if pattern.fullmatch(text):
            return action
    return None


class FastLane:
    """An MCP session held open on its own event loop, for calls without a model.

    Strands' own call_tool_sync took three to eight seconds per call against
    AgentCore, apparently paying the runtime session wake-up each time. Holding
    one session open and reusing it answers in about 370 ms, which is the
    difference between "next" feeling instant and feeling broken.

    A background thread owns the loop so that synchronous request handling can
    borrow the session without an event loop of its own.
    """

    def __init__(self, timeout: int = 60) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._session = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="fast-lane", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("the MCP session did not open in time")
        if self._error is not None:
            raise self._error

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with mcp_client.session() as session:
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            self._error = exc
            self._ready.set()

    def call(self, name: str, arguments: dict) -> dict | None:
        if self._session is None:
            raise RuntimeError("the fast lane has no open session")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments), self._loop
        )
        return future.result(timeout=30)

    def close(self) -> None:
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=10)


class Conversation:
    """One browser session: an agent, an open MCP session, and a place in a repair."""

    def __init__(self) -> None:
        self.tools = ha.build_tools()
        # The Agent starts and keeps the MCP session open; starting it here too
        # raises "the client session is currently running". The fast path then
        # borrows that same open session via call_tool_sync.
        self.agent = Agent(
            model=ha.build_model(),
            tools=[self.tools],
            system_prompt=ha.SYSTEM_PROMPT,
            callback_handler=None,
        )
        self.lane = FastLane()
        self.repair: str | None = None
        self.step: int | None = None
        self.offer: dict | None = None
        self.last_used = time.time()

    def close(self) -> None:
        for shutdown in (self.lane.close, lambda: self.tools.stop(None, None, None)):
            try:
                shutdown()
            except Exception:  # noqa: BLE001 - closing must never raise at teardown
                pass

    # -- state we need for the fast path ------------------------------------

    def _remember(self, data: dict | None) -> None:
        """Track the repair and step, so "next" knows what it is advancing."""
        if not isinstance(data, dict):
            return
        if data.get("finished"):
            self.repair = self.step = None
            return
        if data.get("repair"):
            self.repair = data["repair"]
        if isinstance(data.get("step_number"), int):
            self.step = data["step_number"]

        # A diagnosis ends by offering a fix. Remember it, so that saying yes
        # starts the real walkthrough instead of leaving the model to answer
        # from memory - which it did, once, reciting a repair step that came
        # from no manual at all.
        if data.get("found") and data.get("causes"):
            fix = next((c for c in data["causes"] if c.get("fix_available")), None)
            self.offer = (
                {"appliance": data.get("nickname", ""), "task": fix["fix"]} if fix else None
            )
        elif data.get("started") or data.get("active"):
            self.offer = None

    # -- the two paths ------------------------------------------------------

    def _fast(self, action: str, said: str) -> dict:
        started = time.perf_counter()
        result = self.lane.call(
            "navigate_repair",
            # The fast path passes the person's words through untouched, which is
            # what lets a safety gate clear at all.
            {"action": action, "repair": self.repair, "step": self.step, "said": said},
        )
        ms = (time.perf_counter() - started) * 1000
        data = _first_json(result)
        self._remember(data)
        return {
            "path": "fast",
            "say": None,  # the browser has the phrasing for steps already
            "tool_calls": [{"name": "navigate_repair", "args": {"action": action}, "ms": round(ms)}],
            "data": data,
            "seconds": round(ms / 1000, 2),
        }

    def _ask_agent(self, said: str) -> dict:
        before = len(self.agent.messages)
        started = time.perf_counter()
        reply = self.agent(said)
        seconds = time.perf_counter() - started

        calls = _exchange(self.agent, before)
        say: str | None = str(reply).strip()
        data = next((c["result"] for c in reversed(calls) if c["result"] is not None), None)

        # A repair may only begin when the person asks for it. The model likes to
        # diagnose and then start the walkthrough in the same breath, which
        # commits someone to opening up an appliance they only asked about. When
        # that happens the diagnosis is kept and the offer is made instead, and
        # the repair simply is not started - nothing here is left to persuasion.
        names = [c["name"] for c in calls]
        if "start_repair" in names and "diagnose_symptom" in names:
            diagnosis = next(c["result"] for c in calls if c["name"] == "diagnose_symptom")
            calls = [c for c in calls if c["name"] != "start_repair"]
            data = diagnosis
            say = None  # the diagnosis card ends by offering, in its own words

        # While a repair is under way, every spoken line has to come from a tool.
        # Twice the model answered a turn with no tool call at all and recited a
        # step from its own memory - once "open the drain filter cover", which is
        # not what the manual says. Rather than trusting it not to, a turn that
        # touched no tool during a repair is thrown away and the current step is
        # read again from the server.
        if self.repair and not calls:
            again = self._fast("repeat", said="")
            again["overridden"] = "the model answered without calling a tool"
            return again

        # Inside a repair the model does not get to choose the words. It called
        # navigate_repair, was told the washer still had to be unplugged, and
        # then said "Now open the drain filter cover" regardless. Repair steps
        # are quoted from a manual a person checked, so when a turn touches
        # start_repair or navigate_repair the step card speaks instead, using
        # the tool's own text. The model still decides which tool to call: that
        # is its job here, and the only one.
        if any(c["name"] in ("start_repair", "navigate_repair") for c in calls):
            say = None

        # Interrupted mid-repair to ask something else, they should not have to
        # wonder whether their place survived. It does, so say so.
        if say and self.repair and self.step:
            say = f"{say} We're still on step {self.step} whenever you're ready."

        self._remember(data)
        return {
            "path": "agent",
            "say": say,
            "tool_calls": [{"name": c["name"], "args": c["args"]} for c in calls],
            "data": data,
            "seconds": round(seconds, 2),
        }

    def _accept_offer(self) -> dict:
        offer = self.offer
        self.offer = None
        started = time.perf_counter()
        result = self.lane.call("start_repair", offer)
        ms = (time.perf_counter() - started) * 1000
        data = _first_json(result)
        self._remember(data)
        return {
            "path": "fast",
            "say": None,  # the step card speaks, including its safety gate
            "tool_calls": [{"name": "start_repair", "args": offer, "ms": round(ms)}],
            "data": data,
            "seconds": round(ms / 1000, 2),
        }

    def leave_repair(self) -> dict:
        """Put a repair down. Nothing is lost: it restarts from the top."""
        self.repair = self.step = None
        self.offer = None
        return {
            "path": "fast",
            "say": "Okay, I'll leave that for now. What else can I help with?",
            "tool_calls": [],
            "data": None,
            "seconds": 0.0,
        }

    def respond(self, said: str) -> dict:
        self.last_used = time.time()

        if self.repair and is_escape(said):
            return self.leave_repair()

        action = fast_action(said)
        if action and self.repair:
            return self._fast(action, said)

        # Saying yes to an offered repair is answered from the tools, not from
        # the model's memory of what a drain filter usually looks like.
        if self.offer and is_acceptance(said):
            return self._accept_offer()

        return self._ask_agent(said)


def _first_json(result) -> dict | None:
    """The first JSON object in an MCP tool result, if there is one.

    Tool results arrive in two shapes: Strands hands back a plain dict, the MCP
    SDK hands back objects. Both are accepted rather than assuming either.
    """
    if isinstance(result, dict):
        blocks = result.get("content") or []
    else:
        blocks = getattr(result, "content", None) or []
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            continue
    return None


def _exchange(agent: Agent, from_index: int) -> list[dict]:
    """What the agent called this turn, each call paired with what it returned."""
    calls: list[dict] = []
    by_id: dict[str, dict] = {}
    for message in agent.messages[from_index:]:
        for block in message.get("content", []):
            if "toolUse" in block:
                use = block["toolUse"]
                call = {"name": use["name"], "args": use.get("input", {}), "result": None}
                by_id[use.get("toolUseId", "")] = call
                calls.append(call)
            if "toolResult" in block:
                result = block["toolResult"]
                call = by_id.get(result.get("toolUseId", ""))
                for content in result.get("content", []):
                    text = content.get("text")
                    if not text:
                        continue
                    try:
                        parsed = json.loads(text)
                    except (TypeError, ValueError):
                        continue
                    if call is not None:
                        call["result"] = parsed
                    elif calls:
                        calls[-1]["result"] = parsed
    return calls


# One conversation per browser session. Sessions are dropped once they go quiet
# so a long demo session does not leak MCP connections.
IDLE_SECONDS = 1800
_sessions: dict[str, Conversation] = {}

# Building a conversation opens an MCP session, which takes about five seconds.
# The page warms its session on load and the first message can arrive while that
# is still happening: both then saw "no session yet" and built one, and the
# second build failed on list_tools. The visible result was the first turn
# falling back to keyword matching, and the agent - which had never seen that
# turn - guessing the wrong appliance on the next one.
_building = threading.Lock()


def conversation(session_id: str) -> Conversation:
    _drop_idle()
    existing = _sessions.get(session_id)
    if existing is not None:
        return existing
    with _building:
        # Checked again inside the lock: another thread may have built it while
        # this one waited.
        if session_id not in _sessions:
            _sessions[session_id] = Conversation()
        return _sessions[session_id]


def _drop_idle() -> None:
    cutoff = time.time() - IDLE_SECONDS
    for key in [k for k, c in _sessions.items() if c.last_used < cutoff]:
        _sessions.pop(key).close()
