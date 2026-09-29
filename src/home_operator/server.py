import asyncio
import base64
import hmac
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

from home_operator import gate, store, voice

WEB_DIR = Path(__file__).parent / "web"

HOME = store.load_home()

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
    return store.describe_appliance(HOME, appliance, date.today())


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
    return store.maintenance_due(HOME, date.today(), within_days)


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
    return store.diagnose_symptom(HOME, appliance, symptom, date.today())


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
    return store.start_repair(HOME, appliance, task, date.today())


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
    return store.navigate_repair(HOME, action, repair, step, date.today(), said)


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
    return store.log_service(HOME, appliance, task, date.today(), notes)


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
    return store.add_appliance(HOME, kind, brand, model_number, date.today(), room, nickname)


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
    return store.prepare_pro_brief(HOME, appliance, date.today(), symptom)


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

    session = sonic.SonicSession(emit, voice=ws.query_params.get("voice") or sonic.VOICE_ID)
    deadline = time.monotonic() + gate.SESSION_SECONDS
    try:
        await session.start()
        await emit({"type": "ready", "tools": len(session._tools), "voice": session.voice})
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if time.monotonic() > deadline:
                await emit({"type": "error", "code": "time_limit",
                            "error": "That conversation reached its time limit.", "hint": "press Start to begin a new one"})
                break
            if message.get("bytes"):
                await session.send_audio(message["bytes"])
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - the page needs a reason, not a stack trace
        text = f"{type(exc).__name__}: {exc}"
        # The one failure anyone running this will meet: an `aws login` session
        # lasts about a day, and the page used to say only "Disconnected".
        expired = any(w in text for w in ("LoginRefreshRequired", "expired", "NoCredentials", "ExpiredToken"))
        try:
            await emit({
                "type": "error",
                "code": "aws_login" if expired else "server",
                "error": "The server's AWS sign-in has expired." if expired else text,
                "hint": "run `aws login` where the server runs, then press Start" if expired else "check .env and `aws login`",
            })
        except Exception:  # noqa: BLE001
            pass
    finally:
        gate.LIMITS.release()
        await session.close()


def _client(request: Request) -> str:
    # Behind CloudFront every request comes from CloudFront. It appends the
    # viewer's real address last; anything before that the viewer could have
    # written themselves, so only the last one counts towards the guess limit.
    forwarded = request.headers.get("x-forwarded-for", "")
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
    if code and not hmac.compare_digest(gate.token_for(attempt), gate.token_for(code)):
        gate.ATTEMPTS.failed(who)
        return JSONResponse({"ok": False, "error": "That code isn't right."}, status_code=403)
    response = JSONResponse({"ok": True})
    if code:
        https = request.headers.get("cloudfront-forwarded-proto") == "https" or request.url.scheme == "https"
        response.set_cookie(gate.COOKIE, gate.token_for(code), max_age=gate.COOKIE_DAYS * 86400,
                            httponly=True, secure=https, samesite="lax")
    return response


async def ping(request: Request) -> Response:
    return JSONResponse({"ok": True})


async def home(request: Request) -> Response:
    return RedirectResponse("/sim/")


class AccessCode:
    """Holds back the endpoints that reach AWS until the access code is given.

    Plain ASGI rather than Starlette middleware, because it has to cover the
    WebSocket too. A refused socket is accepted and then closed with 4401, so
    the page can tell "needs the code" apart from "the network dropped".
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and gate.is_protected(scope.get("path", "")):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
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
