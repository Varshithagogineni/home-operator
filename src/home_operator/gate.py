"""Who may use the hosted app, and how much of it.

Run on a laptop, none of this applies: with no ACCESS_CODE set, everything is
open, exactly as before. Hosted on a public link, every conversation costs
money in Nova 2 Sonic, so:

  * the endpoints that reach AWS need an access code, entered once and then
    remembered in a cookie signed with a server secret - never the code, and
    nothing the code can be worked back out from;
  * guessing is slowed down: a few wrong codes from one address and it waits,
    and too many from everywhere at once stops all guessing for a while;
  * only CloudFront, carrying a secret header, can reach the server at all;
  * only so many conversations run at once, and each one has a time limit,
    so a tab left open overnight does not talk to Bedrock all night.
"""

import functools
import hashlib
import hmac
import os
import secrets
import threading
import time

from home_operator import auth

COOKIE = "ho_access"
COOKIE_DAYS = 30

# The endpoints that spend money or change the home. The page itself, and
# /ping for health checks, stay open so the code can be asked for at all.
PROTECTED = ("/voice", "/chat", "/speak", "/mcp")

MAX_FAILURES = 8          # wrong codes from one address...
FAILURE_WINDOW = 15 * 60  # ...within this many seconds, then refused until it passes
MAX_FAILURES_ANYWHERE = 100  # and from all addresses together, against rotating addresses

ORIGIN_HEADER = "x-origin-verify"


@functools.lru_cache(maxsize=1)
def _env() -> dict[str, str]:
    return auth.load_env()


def _setting(name: str) -> str | None:
    return os.environ.get(name) or _env().get(name) or None


def access_code() -> str | None:
    return _setting("ACCESS_CODE")


# Signs the cookie. Set from SSM when hosted, so cookies survive a restart;
# otherwise random per process. The first version keyed the signature with the
# code itself, which let anyone who saw a cookie recover the code offline.
_SECRET = (_setting("COOKIE_SECRET") or secrets.token_hex(32)).encode()


def _normalize(code: str) -> str:
    return " ".join((code or "").lower().replace("-", " ").split())


def token_for(code: str) -> str:
    return hmac.new(_SECRET, b"home-operator-access|" + _normalize(code).encode(), hashlib.sha256).hexdigest()


def codes_match(attempt: str, code: str) -> bool:
    return hmac.compare_digest(_normalize(attempt).encode(), _normalize(code).encode())


def from_cloudfront(headers: dict[str, str]) -> bool:
    """Whether a request came through our own CloudFront distribution.

    The security group admits every CloudFront distribution, anyone's. Ours
    adds a secret header; with ORIGIN_SECRET unset (a laptop) this is a no-op.
    """
    expected = _setting("ORIGIN_SECRET")
    return not expected or hmac.compare_digest(headers.get(ORIGIN_HEADER, ""), expected)


def is_protected(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PROTECTED)


def allowed(cookie_value: str | None, code: str | None = None) -> bool:
    code = code if code is not None else access_code()
    if not code:
        return True
    return bool(cookie_value) and hmac.compare_digest(cookie_value, token_for(code))


def cookie_from(headers: dict[str, str]) -> str | None:
    for part in (headers.get("cookie") or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            return value
    return None


class Attempts:
    """Wrong codes per address, so the code cannot simply be guessed."""

    def __init__(self, limit: int = MAX_FAILURES, window: int = FAILURE_WINDOW,
                 overall: int = MAX_FAILURES_ANYWHERE, clock=time.monotonic) -> None:
        self.limit, self.window, self.overall, self.clock = limit, window, overall, clock
        self._failures: dict[str, list[float]] = {}
        self._all: list[float] = []
        self._lock = threading.Lock()

    def blocked(self, who: str) -> bool:
        with self._lock:
            now = self.clock()
            self._all = [t for t in self._all if now - t < self.window]
            recent = [t for t in self._failures.get(who, []) if now - t < self.window]
            if recent:
                self._failures[who] = recent
            else:
                self._failures.pop(who, None)
            return len(recent) >= self.limit or len(self._all) >= self.overall

    def failed(self, who: str) -> None:
        with self._lock:
            self._failures.setdefault(who, []).append(self.clock())
            self._all.append(self.clock())


class Limits:
    """How many conversations may run at once, and how many in a day."""

    def __init__(self, concurrent: int, per_day: int, clock=time.time) -> None:
        self.concurrent, self.per_day, self.clock = concurrent, per_day, clock
        self.active = 0
        self._day = ""
        self._today = 0
        self._lock = threading.Lock()

    def acquire(self) -> str | None:
        """None if a conversation may start, otherwise why not."""
        with self._lock:
            day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
            if day != self._day:
                self._day, self._today = day, 0
            if self.active >= self.concurrent:
                return "busy"
            if self._today >= self.per_day:
                return "daily_limit"
            self.active += 1
            self._today += 1
            return None

    def release(self) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)


def _int_setting(name: str, default: int) -> int:
    value = os.environ.get(name) or auth.load_env().get(name)
    return int(value) if value else default


LIMITS = Limits(
    concurrent=_int_setting("MAX_CONVERSATIONS", 4),
    per_day=_int_setting("MAX_CONVERSATIONS_PER_DAY", 300),
)
# Longer than any repair here, shorter than a tab forgotten overnight.
SESSION_SECONDS = _int_setting("MAX_CONVERSATION_SECONDS", 20 * 60)
ATTEMPTS = Attempts()
