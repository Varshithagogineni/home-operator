"""Entry point for running the MCP server on Amazon Bedrock AgentCore Runtime.

AgentCore Runtime is strict about the shape of an MCP container:

  * it must listen on 0.0.0.0:8000
  * the MCP endpoint must be at /mcp
  * stateless streamable HTTP, because AgentCore adds its own Mcp-Session-Id
    header to keep a client pinned to one runtime session

Nothing else is exposed. The Polly /speak endpoint and the browser simulator
stay in server.py for local use: AgentCore proxies only /mcp.

Two adjustments were needed to make the MCP SDK work behind AgentCore's proxy,
both found by reading CloudWatch logs rather than documentation:

1. DNS-rebinding protection. The SDK rejects any request whose Host header it
   does not recognise, which is the right default for a server bound to
   localhost on a laptop, where a malicious web page could otherwise reach it.
   AgentCore forwards requests with its own internal host name
   (cell01.us-east-1.prod.arp.kepler-analytics.aws.dev), so every call came back
   421 Misdirected Request. Inside the runtime the check protects nothing: the
   container is not routable, and the only way in is through AgentCore, which
   has already validated a Cognito JWT. So it is switched off here, and here
   only - server.py keeps it for local runs.

2. A /ping route. AgentCore health-checks the container and was getting 404s.

Switching off (1) also switches off the SDK's Origin check, and MCP spec
2025-11-25 says a server MUST answer an invalid Origin with 403. AgentCore's
callers are agents, which send no Origin, so OriginCheck puts that one rule back:
no Origin passes, any Origin not in MCP_ALLOWED_ORIGINS gets 403.

Run locally exactly as AgentCore will run it:
    uv run home-operator-mcp
"""

import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from home_operator.server import mcp

HOST = "0.0.0.0"  # noqa: S104 - required by AgentCore Runtime
PORT = 8000


async def ping(request: Request) -> JSONResponse:
    """Health check for the runtime."""
    return JSONResponse({"status": "ok"})


class OriginCheck:
    """403 for a request whose Origin header is not allowed, as the spec requires."""

    def __init__(self, app, allowed: set[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origin = next((v.decode() for k, v in scope.get("headers", []) if k == b"origin"), None)
            if origin and origin not in self.allowed:
                await JSONResponse({"error": "invalid Origin header"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def allowed_origins() -> set[str]:
    return {o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()}


def build_app():
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        host=HOST,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    app.router.routes.append(Route("/ping", ping, methods=["GET"]))
    return OriginCheck(app, allowed_origins())


def main() -> None:
    print(f"MCP endpoint http://{HOST}:{PORT}/mcp")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
