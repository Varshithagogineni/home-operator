"""The server implements MCP spec 2025-11-25, the hackathon's minimum.

Uses the AgentCore entry point, the same app the deployed runtime serves.
"""

import pytest
from starlette.testclient import TestClient

from home_operator import mcp_entry

SPEC = "2025-11-25"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def client():
    with TestClient(mcp_entry.build_app()) as c:
        yield c


def initialize(client, version):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
    }
    r = client.post("/mcp", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_a_current_client_gets_2025_11_25(client):
    result = initialize(client, SPEC)
    assert result["protocolVersion"] == SPEC
    assert result["serverInfo"]["description"]  # Implementation.description, new in 2025-11-25


def test_a_newer_client_is_offered_2025_11_25(client):
    """Spec lifecycle: the server answers with the latest version it supports."""
    assert initialize(client, "2026-07-28")["protocolVersion"] == SPEC


def test_an_unknown_version_is_offered_2025_11_25(client):
    assert initialize(client, "1999-01-01")["protocolVersion"] == SPEC


def test_the_alexa_plus_client_is_still_served(client):
    """Amazon's Alexa+ MCP client lifecycle page shows the client offering 2025-03-26."""
    assert initialize(client, "2025-03-26")["protocolVersion"] == "2025-03-26"


def test_the_eight_tools_are_listed_under_2025_11_25(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={**HEADERS, "MCP-Protocol-Version": SPEC},
    )
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert len(names) == 8
    assert {"start_repair", "navigate_repair", "diagnose_symptom"} <= names


def test_an_unknown_origin_is_refused_with_403(client):
    """2025-11-25: servers MUST respond 403 Forbidden to an invalid Origin header."""
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        headers={**HEADERS, "MCP-Protocol-Version": SPEC, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_an_allowed_origin_is_let_through(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://inspector.example")
    with TestClient(mcp_entry.build_app()) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            headers={**HEADERS, "MCP-Protocol-Version": SPEC, "Origin": "https://inspector.example"},
        )
    assert r.status_code == 200, r.text


def test_bad_tool_input_is_a_tool_error_the_model_can_correct(client):
    """2025-11-25 (SEP-1303): input validation errors are tool execution errors, not protocol errors."""
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "start_repair", "arguments": {}}},
        headers={**HEADERS, "MCP-Protocol-Version": SPEC},
    )
    body = r.json()
    assert "error" not in body
    assert body["result"]["isError"] is True
