"""Machine-to-machine identity for reaching the MCP server on AgentCore Runtime.

AgentCore Runtime is configured with a CUSTOM_JWT authorizer pointing at our
Cognito user pool. Every MCP request therefore needs a bearer token. We use the
OAuth client_credentials grant: there is no user and no password, the agent
proves it is *our* agent with a client id and secret.

Tokens last an hour, so they are cached. Cognito bills per token request.
"""

import base64
import json
import os
import time
from pathlib import Path

import httpx

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Refresh this many seconds before the token actually expires, so a request
# never goes out holding a token that dies in flight.
EXPIRY_MARGIN = 60


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Read the gitignored .env. Kept tiny on purpose: no extra dependency."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _setting(name: str, env: dict[str, str]) -> str:
    """Real environment wins over .env, so deployment can override the file."""
    value = os.environ.get(name) or env.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Run the Cognito setup, or copy .env.example to .env."
        )
    return value


_cache: dict[str, tuple[str, float]] = {}


def get_token(force: bool = False) -> str:
    """A Cognito access token for the MCP server, cached until it nearly expires."""
    cached = _cache.get("token")
    if cached and not force and cached[1] > time.time():
        return cached[0]

    env = load_env()
    client_id = _setting("COGNITO_CLIENT_ID", env)
    client_secret = _setting("COGNITO_CLIENT_SECRET", env)
    token_url = _setting("COGNITO_TOKEN_URL", env)
    scope = _setting("COGNITO_SCOPE", env)

    # client_credentials sends the client id and secret as HTTP Basic auth.
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = httpx.post(
        token_url,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": scope},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()

    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _cache["token"] = (token, time.time() + expires_in - EXPIRY_MARGIN)
    return token


def claims(token: str) -> dict:
    """Decode a JWT's payload without verifying it.

    Only for looking at our own token while wiring things up: AgentCore is the
    one that verifies the signature. Never trust this for authorisation.
    """
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))
