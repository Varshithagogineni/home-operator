"""Client for the MCP server running on AgentCore Runtime.

The agent talks to its tools through this. Two things make it different from a
plain MCP client:

  * the URL is the AgentCore invocation endpoint, with the runtime ARN
    percent-encoded into the path
  * every request carries a Cognito bearer token, which AgentCore validates
    against the user pool before it proxies anything to our /mcp

Keep one session open for the length of a conversation. AgentCore pins a client
to one runtime session, so an open session is also how in-progress repair state
stays alive between turns.
"""

from contextlib import asynccontextmanager

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from home_operator import auth

# AgentCore holds a request open while a tool runs; be patient but not forever.
TIMEOUT = 60


def remote_url() -> str:
    env = auth.load_env()
    return auth._setting("AGENTCORE_MCP_URL", env)


@asynccontextmanager
async def session(url: str | None = None):
    """An initialised MCP session against the deployed server."""
    url = url or remote_url()
    headers = {
        "Authorization": f"Bearer {auth.get_token()}",
        "Content-Type": "application/json",
    }
    http_client = httpx2.AsyncClient(headers=headers, timeout=TIMEOUT)
    async with http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client
