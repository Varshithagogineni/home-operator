import asyncio
import base64
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.staticfiles import StaticFiles

from home_operator import gate, household, store, voice

WEB_DIR = Path(__file__).parent / "web"

# The checked manual data plus whatever people have changed since. Kept in
# DynamoDB when HOME_TABLE is set, so a logged job survives a restart.
HOUSEHOLD = household.Household()


def _changing(fn):
    """Run a tool that adds to the household, and keep what it added."""
    home = HOUSEHOLD.load()
    before = {"service_log": list(home["service_log"]), "appliances": list(home["appliances"])}
    result = fn(home)
    HOUSEHOLD.save(before, home)
    return result

mcp = MCPServer(
    name="home-operator",
    title="Home Operator",
    version="0.1.0",
    instructions=(
        "Hands-free help with the appliances in this home: what each one is, "
        "which replacement parts it takes, and what maintenance is due."
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(
    title="Look up an appliance",
    description=(
        "Look up one appliance in this home. Returns its model number, warranty status, "
        "the replacement parts it takes (such as filter sizes), and its most recent service. "
        "If nothing matches, or several appliances match, returns the options to ask about."
        " If the reply contains say_first, that is checked safety wording: speak it"
        " first, word for word, before anything else."
    ),
    annotations=READ_ONLY,
)
def get_appliance(
    appliance: Annotated[
        str,
        Field(description='The appliance as the person said it, e.g. "furnace", "the fridge", or "kitchen dishwasher".'),
    ],
) -> dict:
    return store.describe_appliance(HOUSEHOLD.load(), appliance, date.today())


@mcp.tool(
    title="Check maintenance due",
    description=(
        "Each item says who it is for: who is \"homeowner\" for a job someone can do themselves, "
        "and \"dealer\" for one the manufacturer says needs a trained technician - say so rather "
        "than telling someone to inspect their own heat exchanger. "
        "List home maintenance that is overdue, and tasks coming due soon, across every "
        "appliance in this home. Overdue items are sorted most overdue first."
        " If the reply contains say_first, that is checked safety wording: speak it"
        " first, word for word, before anything else."
    ),
    annotations=READ_ONLY,
)
def get_maintenance_due(
    within_days: Annotated[
        int,
        Field(description="How many days ahead to look for upcoming tasks. Overdue tasks are always included.", ge=0, le=365),
    ] = 30,
) -> dict:
    return store.maintenance_due(HOUSEHOLD.load(), date.today(), within_days)


@mcp.tool(
    title="Diagnose a symptom",
    description=(
        "Given an appliance and what it is doing wrong, return the likely causes in order, "
        "with the repair available for each and when that repair was last done. "
        "Use this before starting a repair."
    ),
    annotations=READ_ONLY,
)
def diagnose_symptom(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "dishwasher" or "the furnace".')],
    symptom: Annotated[str, Field(description='What it is doing, in the person\'s own words, e.g. "it will not drain".')],
) -> dict:
    return store.diagnose_symptom(HOUSEHOLD.load(), appliance, symptom, date.today())


@mcp.tool(
    title="Start a repair",
    description=(
        "Begin a step-by-step repair and return the first step, along with the tools needed, "
        "a safety note and how many steps there are. The reply includes a repair id and a "
        "step_number: pass both to navigate_repair to move through the steps. "
        "Only call this once the person has asked to be walked through the repair. If they "
        "have just described a problem, diagnose it and offer first, then wait for them to "
        "agree: starting a repair unasked commits someone to opening up an appliance."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def start_repair(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "dishwasher".')],
    task: Annotated[str, Field(description='The repair to walk through, e.g. "clean the filter".')],
) -> dict:
    return store.start_repair(HOUSEHOLD.load(), appliance, task, date.today())


@mcp.tool(
    title="Move through a repair",
    description=(
        "Move through a repair that is under way. This tool remembers nothing, so say which "
        "repair and which step: pass the repair id and step_number exactly as the last reply gave "
        "them. Use next to advance, back for the previous step, repeat to hear the current step "
        "again, and done to clear a safety gate. A step with awaiting_confirmation true is a "
        "safety gate: it will not advance on next, only on done, and only once the person has "
        "actually confirmed it is safe. Finishing the last step records the service."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def navigate_repair(
    action: Annotated[str, Field(description='One of "next", "back", "repeat", or "done" to confirm a safety gate.')] = "next",
    repair: Annotated[str, Field(description="The repair id from the previous reply.")] = "",
    step: Annotated[int, Field(description="The step_number from the previous reply.")] = 1,
    said: Annotated[str, Field(description=(
        "What the person actually said, word for word, when they are confirming a safety gate. "
        "Only their own words clear a gate, so pass exactly what you heard and never invent it. "
        "A vague yes is not a confirmation that a machine is switched off."
    ))] = "",
) -> dict:
    # Finishing the last step logs the service, so this one can change the household too.
    return _changing(lambda home: store.navigate_repair(home, action, repair, step, date.today(), said))


@mcp.tool(
    title="Log completed service",
    description=(
        "Record that maintenance or a repair was done today, so future overdue checks are accurate. "
        "Returns when the task is next due."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def log_service(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "fridge".')],
    task: Annotated[str, Field(description='What was done, e.g. "replaced the water filter".')],
    notes: Annotated[str | None, Field(description="Anything worth remembering next time.")] = None,
) -> dict:
    return _changing(lambda home: store.log_service(home, appliance, task, date.today(), notes))


@mcp.tool(
    title="Add an appliance",
    description=(
        "Register an appliance the person owns, from its type, brand and model number, e.g. "
        "\"I just got a Bosch dishwasher, model SHE33T52UC\". Gives it a standard maintenance "
        "schedule and queues a safety recall check. Returns the existing one if the model is already registered."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def add_appliance(
    kind: Annotated[str, Field(description='What it is, e.g. "dishwasher", "fridge" or "washer".')],
    brand: Annotated[str, Field(description='The brand on the label, e.g. "Bosch".')],
    model_number: Annotated[str, Field(description="The model number from the data plate.")],
    room: Annotated[str | None, Field(description='Where it is, e.g. "kitchen".')] = None,
    nickname: Annotated[str | None, Field(description='What the person calls it, e.g. "upstairs washer".')] = None,
) -> dict:
    return _changing(lambda home: store.add_appliance(home, kind, brand, model_number, date.today(), room, nickname))


@mcp.tool(
    title="Brief a repair professional",
    description=(
        "Prepare a short summary to hand to a repair professional: the model, its age and warranty, "
        "the problem, what was already tried today, and recent service. Flags open safety recalls, "
        "since the manufacturer repairs recalled products for free."
    ),
    annotations=READ_ONLY,
)
def prepare_pro_brief(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "dishwasher".')],
    symptom: Annotated[str | None, Field(description='The problem in the person\'s words, e.g. "still won\'t drain".')] = None,
) -> dict:
    return store.prepare_pro_brief(HOUSEHOLD.load(), appliance, date.today(), symptom)


async def speak(request: Request) -> Response:
    body = await request.json()
    audio = await anyio.to_thread.run_sync(voice.synthesize, str(body.get("text", "")))
    if audio is None:
        return JSONResponse({"error": "Amazon Polly is unavailable; use the browser voice."}, status_code=503)
    return Response(audio, media_type="audio/mpeg")


async def chat(request: Request) -> Response:
    """Ask the agent. The simulator's brain, standing in for Alexa+'s.

    Imported here rather than at module scope on purpose: the agent needs AWS
    credentials and the Strands SDK, and the simulator has to keep working
    without either.
    """
    from home_operator import chat as conversations

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "expected JSON"}, status_code=400)

    said = (payload.get("text") or "").strip()
    if not said:
        return JSONResponse({"error": "nothing was said"}, status_code=400)
    session_id = payload.get("session") or "default"

    try:
        talk = await anyio.to_thread.run_sync(conversations.conversation, session_id)
        reply = await anyio.to_thread.run_sync(talk.respond, said)
    except Exception as exc:  # noqa: BLE001 - the browser needs a reason, not a stack trace
        return JSONResponse(
            {"error": f"{type(exc).__name__}: {exc}", "hint": "check .env and `aws login`"},
            status_code=502,
        )
    return JSONResponse(reply)


async def warm(request: Request) -> Response:
    """Open the session and pay the handshake now, not on camera.

    AgentCore takes about five seconds to wake a runtime session for a new
    client. Calling this before a demo moves that wait off the recording.
    """
    from home_operator import chat as conversations

    session_id = request.query_params.get("session", "default")
    started = date.today()
    try:
        talk = await anyio.to_thread.run_sync(conversations.conversation, session_id)
        tools = await anyio.to_thread.run_sync(talk.tools.list_tools_sync)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"warm": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=502)
    return JSONResponse({"warm": True, "tools": len(tools), "as_of": started.isoformat()})


async def voice_socket(ws: WebSocket) -> None:
    """Speech to speech: microphone PCM in, Nova 2 Sonic's voice out.

    Binary frames in either direction are audio: 16 kHz PCM from the browser,
    24 kHz PCM back. Text frames from here are JSON events for the screen.
    Imported lazily like /chat: it needs AWS and the speech dependency group.
    """
    from home_operator import sonic

    await ws.accept()
    sending = asyncio.Lock()

    async def emit(event: dict) -> None:
        async with sending:
            if event.get("type") == "audio":
                await ws.send_bytes(base64.b64decode(event["pcm"]))
            else:
                await ws.send_text(json.dumps(event, default=str))

    refused = gate.LIMITS.acquire()
    if refused:
        await emit({"type": "error", "code": refused, "error": (
            "Home Operator is busy with other conversations right now." if refused == "busy"
            else "Home Operator has reached today's limit of conversations."
        ), "hint": "try again in a few minutes" if refused == "busy" else "try again tomorrow"})
        await ws.close(code=4429)
        return

    # Everything after a slot is taken sits inside the try, so the finally
    # always gives it back; a constructor that raised used to keep it for good.
    session = None
    try:
        session = sonic.SonicSession(emit, voice=ws.query_params.get("voice") or sonic.VOICE_ID)
        deadline = time.monotonic() + gate.SESSION_SECONDS
        await session.start()
        await emit({"type": "ready", "tools": len(session._tools), "voice": session.voice})
        _warm_photo_tools()
        while True:
            # Waits at most until the deadline, so a tab that stops sending
            # audio cannot hold a Sonic stream open past the time limit.
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=max(0.0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                await emit({"type": "error", "code": "time_limit",
                            "error": "That conversation reached its time limit.", "hint": "press Start to begin a new one"})
                break
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.send_audio(message["bytes"])
            elif message.get("text"):
                # The page tells the voice about something that happened on
                # screen - an appliance added from a photo - so it can say so.
                try:
                    note = json.loads(message["text"])
                except ValueError:
                    note = {}
                if note.get("type") == "note" and isinstance(note.get("text"), str):
                    await session.send_note(note["text"][:600])
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - the page needs a reason, not a stack trace
        text = f"{type(exc).__name__}: {exc}"
        # The one failure anyone running this will meet: an `aws login` session
        # lasts about a day, and the page used to say only "Disconnected".
        expired = any(w in text for w in ("LoginRefreshRequired", "expired", "NoCredentials", "ExpiredToken"))
        hosted = bool(gate.access_code())
        print(f"voice session failed: {text}", flush=True)  # the detail stays in the server log
        try:
            await emit({
                "type": "error",
                "code": "aws_login" if expired else "server",
                "error": "The server's AWS sign-in has expired." if expired
                else ("Something went wrong reaching AWS." if hosted else text),
                "hint": "run `aws login` where the server runs, then press Start" if expired
                else ("please try again in a minute" if hosted else "check .env and `aws login`"),
            })
        except Exception:  # noqa: BLE001
            pass
    finally:
        gate.LIMITS.release()
        if session is not None:
            await session.close()


def _client(request: Request) -> str:
    # Behind CloudFront every request comes from CloudFront. It appends the
    # viewer's real address last; anything before that the viewer could have
    # written themselves, so only the last one counts towards the guess limit.
    forwarded = (request.headers.getlist("x-forwarded-for") or [""])[-1]
    return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "?")


async def unlock_status(request: Request) -> Response:
    return JSONResponse({"locked": not gate.allowed(gate.cookie_from(dict(request.headers)))})


async def unlock(request: Request) -> Response:
    who = _client(request)
    if gate.ATTEMPTS.blocked(who):
        return JSONResponse({"ok": False, "error": "Too many tries. Wait a few minutes."}, status_code=429)
    try:
        attempt = str((await request.json()).get("code", ""))
    except ValueError:
        attempt = ""
    code = gate.access_code()
    if code and not gate.codes_match(attempt, code):
        gate.ATTEMPTS.failed(who)
        return JSONResponse({"ok": False, "error": "That code isn't right."}, status_code=403)
    response = JSONResponse({"ok": True})
    if code:
        # A code is only set when hosted, and hosted is always HTTPS to the
        # browser; CloudFront talks plain HTTP to us, so the scheme can't tell.
        response.set_cookie(gate.COOKIE, gate.token_for(code), max_age=gate.COOKIE_DAYS * 86400,
                            httponly=True, secure=True, samesite="lax")
    return response


PHOTO_LIMITS = gate.Limits(concurrent=2, per_day=100)
_photo_tools = None


def _call_tool(name: str, args: dict):
    """An MCP call over one held-open session, opened on first use.

    A fresh session per photo cost about five seconds of AgentCore waking up;
    holding one answers in about 400 ms. Its token lasts an hour, so on any
    failure the session is rebuilt once and the call retried.
    """
    from home_operator import chat as conversations
    global _photo_tools
    for attempt in (1, 2):
        try:
            if _photo_tools is None:
                _photo_tools = conversations.FastLane()
            return conversations._first_json(_photo_tools.call(name, args))
        except Exception:
            if _photo_tools is not None:
                _photo_tools.close()
            _photo_tools = None
            if attempt == 2:
                raise


def _warm_photo_tools() -> None:
    """Open the photo flow's tool session in the background, before it is needed."""
    import threading
    if _photo_tools is None:
        threading.Thread(target=_open_photo_tools, daemon=True).start()


def _open_photo_tools() -> None:
    from home_operator import chat as conversations
    global _photo_tools
    try:
        if _photo_tools is None:
            _photo_tools = conversations.FastLane()
    except Exception:  # noqa: BLE001 - the photo call opens it again if this failed
        pass


async def appliance_photo(request: Request) -> Response:
    """Add an appliance from a photo of its label, the way Alexa+ would hand it over.

    Nova reads the label (standing in for Alexa+'s own photo reading), the
    add_appliance tool on AgentCore registers it, and the government recall
    database is checked for that model, live.
    """
    from home_operator import photo

    body = await request.body()
    if len(body) > photo.MAX_BYTES * 1.4:
        return JSONResponse({"error": "That photo is too large. Try one under 8 MB."}, status_code=413)
    refused = PHOTO_LIMITS.acquire()
    if refused:
        return JSONResponse({"error": "Too many photos right now. Try again in a few minutes."}, status_code=429)
    timings = {}
    try:
        image, media = photo.decode_upload(body, request.headers.get("content-type", ""))
        t = time.perf_counter()
        label = await anyio.to_thread.run_sync(photo.read_label, image, media)
        timings["read_label_ms"] = round((time.perf_counter() - t) * 1000)
        if not label["found"]:
            return JSONResponse({"label": label, "timings": timings})
        t = time.perf_counter()
        added = await anyio.to_thread.run_sync(_call_tool, "add_appliance", {
            "kind": label["kind"], "brand": label["brand"], "model_number": label["model_number"]})
        timings["add_appliance_ms"] = round((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        appliance = {"brand": label["brand"], "model_number": label["model_number"], "category": store._category(label["kind"])}
        recall = await anyio.to_thread.run_sync(photo.recall_check, appliance)
        timings["recall_check_ms"] = round((time.perf_counter() - t) * 1000)
        if recall.get("matches"):
            recall["say_first"] = store.recall_sentence((added or {}).get("nickname", label["kind"]), recall["matches"][0])
        return JSONResponse({"label": label, "added": added, "recall": recall, "timings": timings})
    except Exception as exc:  # noqa: BLE001 - the page needs a reason
        print(f"appliance photo failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": "The photo could not be processed. Please try again."}, status_code=502)
    finally:
        PHOTO_LIMITS.release()


async def ping(request: Request) -> Response:
    return JSONResponse({"ok": True})


async def home(request: Request) -> Response:
    # Keep the query: a shared link's ?code= rides through this redirect.
    query = request.url.query
    return RedirectResponse("/sim/" + (f"?{query}" if query else ""))


class AccessCode:
    """Holds back the endpoints that reach AWS until the access code is given.

    Plain ASGI rather than Starlette middleware, because it has to cover the
    WebSocket too. A refused socket is accepted and then closed with 4401, so
    the page can tell "needs the code" apart from "the network dropped".
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if not gate.from_cloudfront(headers):
                if scope["type"] == "websocket":
                    await receive()
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await JSONResponse({"error": "not found"}, status_code=404)(scope, receive, send)
                return
        if scope["type"] in ("http", "websocket") and gate.is_protected(scope.get("path", "")):
            if not gate.allowed(gate.cookie_from(headers)):
                if scope["type"] == "websocket":
                    await receive()
                    await send({"type": "websocket.accept"})
                    await send({"type": "websocket.close", "code": 4401})
                    return
                response = JSONResponse({"error": "access code required"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app():
    """The MCP endpoint at /mcp, the Polly voice at /speak, and the simulator at /sim."""
    app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    app.router.routes.append(Route("/speak", speak, methods=["POST"]))
    app.router.routes.append(Route("/chat", chat, methods=["POST"]))
    app.router.routes.append(Route("/chat/warm", warm, methods=["GET"]))
    app.router.routes.append(WebSocketRoute("/voice", voice_socket))
    app.router.routes.append(Route("/unlock", unlock_status, methods=["GET"]))
    app.router.routes.append(Route("/unlock", unlock, methods=["POST"]))
    app.router.routes.append(Route("/ping", ping, methods=["GET"]))
    app.router.routes.append(Route("/appliance-photo", appliance_photo, methods=["POST"]))
    app.router.routes.append(Route("/", home, methods=["GET"]))
    app.router.routes.append(
        Mount("/sim", app=StaticFiles(directory=WEB_DIR, html=True), name="sim")
    )
    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"MCP endpoint  http://{host}:{port}/mcp")
    print(f"Simulator     http://{host}:{port}/sim/")
    print(f"Classic       http://{host}:{port}/sim/classic.html")
    if gate.access_code():
        print("Access code   required for /voice, /chat, /speak and /mcp")
    # proxy_headers: behind CloudFront, trust its forwarded address and scheme.
    uvicorn.run(AccessCode(build_app()), host=host, port=port, log_level="info",
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
