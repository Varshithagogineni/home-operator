"""The hosted app's access code and limits. With no code set, nothing changes."""


from starlette.testclient import TestClient

from home_operator import gate, server


def test_no_code_means_open_like_before():
    assert gate.allowed(None, code="")


def test_the_cookie_is_signed_with_a_server_secret_not_the_code():
    """The first version keyed the cookie with the code, so a seen cookie gave
    the code away offline. Now it depends on a secret that never leaves AWS."""
    import hashlib, hmac
    token = gate.token_for("amber river 42")
    assert "amber" not in token
    guess = hmac.new(b"amber river 42", b"home-operator-access", hashlib.sha256).hexdigest()
    assert token != guess
    assert gate.allowed(token, code="amber river 42")
    assert gate.allowed(token, code="Amber-River 42")  # typed loosely, same code
    assert not gate.allowed(token, code="other code")
    assert not gate.allowed(None, code="amber river 42")


def test_only_the_endpoints_that_reach_aws_are_protected():
    for path in ("/voice", "/chat", "/chat/warm", "/speak", "/mcp", "/appliance-photo"):
        assert gate.is_protected(path), path
    for path in ("/", "/sim/", "/sim/index.html", "/ping", "/unlock", "/voiceover"):
        assert not gate.is_protected(path), path


def test_guessing_is_slowed_down():
    now = [0.0]
    attempts = gate.Attempts(limit=3, window=60, clock=lambda: now[0])
    for _ in range(3):
        attempts.failed("1.2.3.4")
    assert attempts.blocked("1.2.3.4")
    assert not attempts.blocked("5.6.7.8")
    now[0] = 61
    assert not attempts.blocked("1.2.3.4")


def test_rotating_addresses_still_hits_an_overall_limit():
    attempts = gate.Attempts(limit=8, window=60, overall=5, clock=lambda: 0)
    for i in range(5):
        attempts.failed(f"10.0.0.{i}")
    assert attempts.blocked("203.0.113.9")


def test_only_our_cloudfront_reaches_the_server(monkeypatch):
    monkeypatch.setenv("ORIGIN_SECRET", "s3cret")
    assert not gate.from_cloudfront({})
    assert not gate.from_cloudfront({"x-origin-verify": "wrong"})
    assert gate.from_cloudfront({"x-origin-verify": "s3cret"})
    client = TestClient(server.AccessCode(server.build_app()))
    assert client.get("/sim/").status_code == 404
    assert client.get("/sim/", headers={"x-origin-verify": "s3cret"}).status_code == 200


def test_conversations_are_limited_at_once_and_per_day():
    limits = gate.Limits(concurrent=2, per_day=3, clock=lambda: 0)
    assert limits.acquire() is None and limits.acquire() is None
    assert limits.acquire() == "busy"
    limits.release()
    assert limits.acquire() is None
    limits.release()
    assert limits.acquire() == "daily_limit"


def _client(monkeypatch, code):
    monkeypatch.setenv("ACCESS_CODE", code)
    gate.ATTEMPTS = gate.Attempts()
    # HTTPS, as through CloudFront: the cookie is Secure and a plain-HTTP
    # client would never send it back.
    return TestClient(server.AccessCode(server.build_app()), base_url="https://testserver")


def test_the_page_opens_but_the_tools_wait_for_the_code(monkeypatch):
    client = _client(monkeypatch, "amber river 42")
    assert client.get("/sim/").status_code == 200
    assert client.get("/unlock").json() == {"locked": True}
    assert client.post("/speak", json={"text": "hi"}).status_code == 401
    assert client.post("/appliance-photo", content=b"data:image/png;base64,AA==").status_code == 401
    assert client.post("/unlock", json={"code": "wrong"}).status_code == 403
    assert client.post("/unlock", json={"code": "amber river 42"}).json() == {"ok": True}
    assert client.get("/unlock").json() == {"locked": False}


def test_the_voice_socket_says_it_needs_the_code(monkeypatch):
    client = _client(monkeypatch, "amber river 42")
    with client.websocket_connect("/voice") as ws:
        message = ws.receive()
    assert message["type"] == "websocket.close" and message["code"] == 4401


def test_a_forged_forwarded_address_does_not_reset_the_guess_limit(monkeypatch):
    client = _client(monkeypatch, "amber river 42")
    for i in range(gate.MAX_FAILURES):
        client.post("/unlock", json={"code": "wrong"}, headers={"x-forwarded-for": f"10.0.0.{i}, 9.9.9.9"})
    r = client.post("/unlock", json={"code": "amber river 42"}, headers={"x-forwarded-for": "10.9.9.9, 9.9.9.9"})
    assert r.status_code == 429


def test_root_opens_the_app(monkeypatch):
    client = _client(monkeypatch, "")
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/sim/"
    # A shared link's code must survive the redirect; it once did not.
    r = client.get("/?code=abc-123", follow_redirects=False)
    assert r.headers["location"] == "/sim/?code=abc-123"
