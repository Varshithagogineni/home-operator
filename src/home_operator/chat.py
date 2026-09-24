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
TRAILING = re.compile(r"\s+(please|now|then|thanks|thank you)$")
LEADING = re.compile(r"^(ok|okay|alright|right|and|so|um|uh|yeah|yep)[,\s]+")


def fast_action(said: str) -> str | None:
    """The navigation action a phrase means, or None to let the model decide.

    Deliberately conservative: anything that could mean something else goes to
    the model. Sending a real question down the fast path would answer the wrong
    thing, which is worse than being slow.
    """
    text = said.strip().lower().rstrip(".!?")
    text = text.replace("'", "")
    text = LEADING.sub("", text)
    text = TRAILING.sub("", text).strip()
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

    # -- the two paths ------------------------------------------------------

    def _fast(self, action: str) -> dict:
        started = time.perf_counter()
        result = self.lane.call(
            "navigate_repair",
            {"action": action, "repair": self.repair, "step": self.step},
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
        calls, data = _exchange(self.agent, before)
        self._remember(data)
        return {
            "path": "agent",
            "say": str(reply).strip(),
            "tool_calls": calls,
            "data": data,
            "seconds": round(seconds, 2),
        }

    def respond(self, said: str) -> dict:
        self.last_used = time.time()
        action = fast_action(said)
        if action and self.repair:
            return self._fast(action)
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


def _exchange(agent: Agent, from_index: int) -> tuple[list[dict], dict | None]:
    """What the agent called this turn, and the last thing a tool returned."""
    calls: list[dict] = []
    data: dict | None = None
    for message in agent.messages[from_index:]:
        for block in message.get("content", []):
            if "toolUse" in block:
                use = block["toolUse"]
                calls.append({"name": use["name"], "args": use.get("input", {})})
            if "toolResult" in block:
                for content in block["toolResult"].get("content", []):
                    text = content.get("text")
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                    except (TypeError, ValueError):
                        pass
    return calls, data


# One conversation per browser session. Sessions are dropped once they go quiet
# so a long demo session does not leak MCP connections.
IDLE_SECONDS = 1800
_sessions: dict[str, Conversation] = {}


def conversation(session_id: str) -> Conversation:
    _drop_idle()
    if session_id not in _sessions:
        _sessions[session_id] = Conversation()
    return _sessions[session_id]


def _drop_idle() -> None:
    cutoff = time.time() - IDLE_SECONDS
    for key in [k for k, c in _sessions.items() if c.last_used < cutoff]:
        _sessions.pop(key).close()
