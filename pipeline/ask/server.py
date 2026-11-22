"""The API behind the site's Ask and Assess pages (a FastAPI app factory).

Three routes; :mod:`pipeline.webapp` mounts them under ``/api`` and is the
one way to run them (``python -m pipeline.webapp``):

* ``POST /ask``    — a question answered by an LLM from retrieved KG nodes.
  The server holds the model key; the browser never sees it.
* ``POST /assess`` — an audit of one public GitHub repository.
* ``GET  /health`` — ``{"ok": true}`` and nothing else.

Both POST routes are open to anyone and cost something (model tokens, or
GitHub requests and a worker), so each is bounded four ways:

1. **Per client**: a number of calls per hour per client address.
2. **At once**: a fixed number of running calls (4 questions, 2 audits);
   further calls get 429 at once instead of queueing. The work runs in the
   route's own small thread pool, so it cannot starve the event loop or
   the threads that serve the static site.
3. **Per day**: a budget for the whole process that starts again at
   midnight UTC. For Ask it is reserved *before* retrieval and before the
   model is called.
4. **Per call**: a wall-clock limit (and for audits the fetch caps in
   :mod:`pipeline.audit.analyzer`). Audit reports are kept for a day per
   ``owner/repo``; a repeat costs nothing.

How far the client address can be trusted. The app counts a caller under
the address of the socket that connected to it. ``X-Forwarded-For`` is
read only when that socket belongs to a proxy we trust
(``FORWARDED_ALLOW_IPS``; default: loopback only), because anyone who can
reach the app directly can write any header. From a trusted proxy we take
the entry that the proxy itself appended (the last one; ``SAICA_TRUSTED_PROXY_HOPS``
counts from the right when several trusted proxies are chained) and ignore
everything to its left, which the visitor controls. See :func:`client_key`.

What cannot be known from here: behind Replit's proxy the app never sees
the visitor's socket, and we have not verified from which address that
proxy connects or how it builds the header. Until ``FORWARDED_ALLOW_IPS``
names that proxy in the deployment, its header is ignored and every
visitor is counted under the proxy's own address: the per-client limit
then acts as a second global limit. It can lock people out; it cannot be
bypassed. Setting ``FORWARDED_ALLOW_IPS=*`` is right only if the app is
reachable through the proxy and nothing else. The daily budget does not
depend on the address at all; it is what bounds spend. It lives in this
process: with several autoscale instances the real ceiling is the budget
times the number of instances.

Other hardening (review 2026-11-21, H3): request bodies over 8 kB are
refused before they are parsed; validation errors do not echo the input;
the interactive docs are off unless ``SAICA_API_DOCS=1``; CORS is limited
to the site's origins; errors carry a generic text and a request id, and
the exception stays in the server log.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import time
import uuid
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from pipeline.ask.context import NodeContext, build_prompt, hybrid_retrieve, hydrate
from pipeline.audit.analyzer import (
    AuditError,
    DetectionAborted,
    FetchUnavailable,
    RepoNotFound,
    RepoTooLarge,
    audit_repo,
    parse_repo_url,
)
from pipeline.cost_caps import CallBudget, CostCapExceeded, DailyBudget

log = logging.getLogger(__name__)

DEFAULT_PORT = 4322

# Retrieval fan-out. K=20 gives the coverage rule of the prompt enough
# candidates to find tools that are tagged for the failure mode in question.
DEFAULT_K = 20

# Output cap of one answer. Sized for a reasoning model, whose hidden
# trace also counts against it.
KIMI_MAX_TOKENS = 6144
KIMI_TEMPERATURE = 0.2
# One model call may wait this long, and is retried at most once.
LLM_TIMEOUT_SECONDS = 60.0
LLM_MAX_RETRIES = 1

MAX_BODY_BYTES = 8192

# Origins that may call the API from a browser. The site itself calls it
# same-origin (in development through the dev server's proxy), so this
# list only matters for a page served from another origin.
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "https://saica.ai",
    "https://www.saica.ai",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:4321",
    "http://127.0.0.1:4321",
)

# Peers whose ``X-Forwarded-*`` headers are believed, unless
# ``FORWARDED_ALLOW_IPS`` says otherwise: this machine only.
DEFAULT_TRUSTED_PROXIES: tuple[str, ...] = ("127.0.0.0/8", "::1/128")

BAD_REPO_URL = "repo_url must look like https://github.com/<owner>/<repo>"
GENERIC_ERROR = "The service could not complete the request."
BUSY = "The service is busy. Please try again in a moment."


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        log.warning("invalid %s=%r; using %d", name, raw, default)
        return default


def trusted_proxies_from_env() -> tuple[str, ...]:
    """``FORWARDED_ALLOW_IPS`` as a tuple: addresses, networks, or ``*``.

    Unset or empty means :data:`DEFAULT_TRUSTED_PROXIES`. Entries that are
    not an address or a network are dropped with a warning.
    """
    raw = os.environ.get("FORWARDED_ALLOW_IPS", "")
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not entries:
        return DEFAULT_TRUSTED_PROXIES
    out: list[str] = []
    for entry in entries:
        if entry == "*":
            return ("*",)
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            log.warning("FORWARDED_ALLOW_IPS: ignoring %r", entry)
            continue
        out.append(entry)
    return tuple(out) or DEFAULT_TRUSTED_PROXIES


def parse_address(text: str | None):
    """An IP address from ``1.2.3.4``, ``1.2.3.4:567``, ``::1``,
    ``[::1]`` or ``[::1]:567``; ``None`` for anything else."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]  # IPv4 with a port
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped if mapped is not None else address


def is_trusted_proxy(peer: str | None, trusted: tuple[str, ...]) -> bool:
    """Is the socket's peer one of the proxies whose headers we believe?"""
    if "*" in trusted:
        return True
    address = parse_address(peer)
    if address is None:
        return False
    for entry in trusted:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except (ValueError, TypeError):
            continue
    return False


@dataclass(frozen=True)
class Settings:
    """Limits of the API. ``from_env`` reads them once, at start-up."""

    ask_daily_calls: int = 50
    ask_daily_tokens: int = 600_000
    ask_per_client_hour: int = 10
    ask_concurrency: int = 4
    ask_wall_clock: float = 150.0
    assess_daily_calls: int = 100
    assess_per_client_hour: int = 10
    assess_concurrency: int = 2
    assess_wall_clock: float = 30.0
    assess_cache_seconds: float = 86_400.0
    assess_cache_entries: int = 256
    trusted_proxy_hops: int = 1
    trusted_proxies: tuple[str, ...] = DEFAULT_TRUSTED_PROXIES
    assess_negative_cache_seconds: float = 300.0
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    docs: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            o.strip().rstrip("/")
            for o in os.environ.get("SAICA_CORS_ORIGINS", "").split(",")
            if o.strip()
        )
        return cls(
            ask_daily_calls=_env_int("SAICA_ASK_BUDGET", cls.ask_daily_calls),
            ask_daily_tokens=_env_int("SAICA_ASK_TOKEN_BUDGET", cls.ask_daily_tokens),
            ask_per_client_hour=_env_int(
                "SAICA_ASK_PER_CLIENT", cls.ask_per_client_hour
            ),
            ask_concurrency=_env_int(
                "SAICA_ASK_CONCURRENCY", cls.ask_concurrency, minimum=1
            ),
            assess_daily_calls=_env_int("SAICA_ASSESS_BUDGET", cls.assess_daily_calls),
            assess_per_client_hour=_env_int(
                "SAICA_ASSESS_PER_CLIENT", cls.assess_per_client_hour
            ),
            assess_concurrency=_env_int(
                "SAICA_ASSESS_CONCURRENCY", cls.assess_concurrency, minimum=1
            ),
            trusted_proxy_hops=_env_int(
                "SAICA_TRUSTED_PROXY_HOPS", cls.trusted_proxy_hops, minimum=1
            ),
            trusted_proxies=trusted_proxies_from_env(),
            cors_origins=origins or DEFAULT_CORS_ORIGINS,
            docs=os.environ.get("SAICA_API_DOCS") == "1",
        )


# ---------------------------------------------------------------------------
# Small limiters (all in-process, all thread-safe)
# ---------------------------------------------------------------------------


class Slots:
    """At most ``size`` holders at once; never waits."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._held = 0
        self._lock = Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._held >= self._size:
                return False
            self._held += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._held = max(0, self._held - 1)

    @property
    def held(self) -> int:
        return self._held


class PerClientLimit:
    """``max_calls`` per ``window`` seconds for each key (sliding window).

    Remembers at most ``max_clients`` keys; the least recently seen is
    forgotten first. ``max_calls == 0`` refuses everything.
    """

    def __init__(
        self,
        max_calls: int,
        window: float = 3600.0,
        *,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_calls
        self._window = window
        self._max_clients = max_clients
        self._clock = clock
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """Count one call for ``key``; False when it is over its limit."""
        now = self._clock()
        with self._lock:
            calls = self._seen.pop(key, None) or deque()
            while calls and now - calls[0] >= self._window:
                calls.popleft()
            allowed = len(calls) < self._max
            if allowed:
                calls.append(now)
            if calls:
                self._seen[key] = calls
                while len(self._seen) > self._max_clients:
                    self._seen.popitem(last=False)
            return allowed


class DayCache:
    """A small time-limited cache (audit reports per ``owner/repo``)."""

    def __init__(
        self,
        ttl: float,
        max_entries: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored, value = item
            if self._clock() - stored >= self._ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)


def _bucket(address) -> str:
    """IPv6 callers are counted per /64: one subscriber usually holds one."""
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address)
    return str(address)


def client_key(
    scope_client: tuple[str, int] | None,
    forwarded_for: list[str] | str | None,
    hops: int = 1,
    trusted: tuple[str, ...] = DEFAULT_TRUSTED_PROXIES,
) -> str:
    """The address to count a caller under. See the module docstring.

    The socket's peer address, unless that peer is a trusted proxy and
    sent ``X-Forwarded-For``. The header is ``client, proxy1, proxy2``:
    each proxy appends the address that connected to it, so with ``hops``
    trusted proxies in front of the app the entry ``hops`` from the right
    is the one the outermost of them wrote. Entries further left come from
    the caller and are ignored. All lines of the header are read (a caller
    can send a second line); an entry may carry a port. If the header has
    fewer entries than ``hops`` or the entry is not an address, the peer
    itself is used: a caller never gets a bucket of its own by sending
    something unreadable.
    """
    peer = parse_address(scope_client[0]) if scope_client else None
    if peer is None:
        return "unknown"
    lines = (
        [forwarded_for] if isinstance(forwarded_for, str) else list(forwarded_for or [])
    )
    if not lines or not is_trusted_proxy(str(peer), trusted):
        return _bucket(peer)
    parts = [p.strip() for line in lines for p in line.split(",") if p.strip()]
    if len(parts) < hops:
        return _bucket(peer)
    address = parse_address(parts[-hops])
    return _bucket(address if address is not None else peer)


# ---------------------------------------------------------------------------
# ASGI guard: request id and body-size limit
# ---------------------------------------------------------------------------


class ApiGuard:
    """Gives every request an id and refuses bodies over ``max_body`` bytes.

    The body is read here, up to the limit, before the app sees the
    request: a declared ``Content-Length`` over the limit is refused
    without reading anything, and a body that grows past the limit while
    it streams in (chunked upload) is refused at that point. The app then
    gets the small body it was promised.
    """

    def __init__(self, app, max_body: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("ascii"))
                )
            await send(message)

        async def refuse(status: int, detail: str) -> None:
            response = JSONResponse(
                {"detail": detail, "request_id": request_id}, status_code=status
            )
            await response(scope, receive, send_with_id)

        too_large = f"The request body is larger than {self.max_body} bytes."
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_body:
                    await refuse(413, too_large)
                    return
            except ValueError:
                await refuse(400, "The Content-Length header is not a number.")
                return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before sending a request
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_body:
                await refuse(413, too_large)
                return
            chunks.append(body)
            if not message.get("more_body"):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": b"".join(chunks),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay, send_with_id)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class Question(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AssessRequest(BaseModel):
    """Input for the /assess endpoint — a public GitHub repo URL."""

    repo_url: str = Field(..., min_length=1, max_length=500)


class Citation(BaseModel):
    id: str
    type: str
    name: str
    snippet: str
    similarity: float
    url: str


class Answer(BaseModel):
    answer: str
    citations: list[Citation]
    # The field keeps its old name; it holds the tokens of whatever model answered.
    kimi_tokens_used: int
    model: str


# ---------------------------------------------------------------------------
# Default collaborators
# ---------------------------------------------------------------------------


def _default_find_similar(
    question: str,
    k: int,
    *,
    node_type: str | None = None,
) -> list[tuple[str, float]]:
    """Thin wrapper around ``pipeline.embeddings.query.find_similar``.

    Imported lazily so this module imports without the embedding stack.
    """
    from pipeline.embeddings.query import find_similar  # local import

    return list(find_similar(question, k=k, node_type=node_type))


def _default_kimi_call(prompt: str) -> tuple[str, Any]:
    """One chat completion; returns ``(answer_text, raw_response)``.

    The client comes from :func:`pipeline.extract.kimi.get_client` (an
    OpenAI-compatible endpoint named by the ``AZURE_KIMI_*`` variables),
    with a 60-second timeout and one retry instead of the SDK's ten
    minutes and two.
    """
    from pipeline.config import load_env_once
    from pipeline.extract.kimi import _model_name, get_client

    load_env_once()
    client = get_client().with_options(
        timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
    )
    resp = client.chat.completions.create(
        model=_model_name(),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=KIMI_MAX_TOKENS,
        temperature=KIMI_TEMPERATURE,
    )
    content = resp.choices[0].message.content or ""
    return content.strip(), resp


@dataclass
class _AskRun:
    """What one question did, so the budget can be settled afterwards."""

    model_called: bool = False
    tokens: int = 0
    nodes: list[NodeContext] = field(default_factory=list)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    find_similar=_default_find_similar,
    kimi_call=_default_kimi_call,
    budget: CallBudget | None = None,
    k: int = DEFAULT_K,
    audit: Callable[[str], Any] = audit_repo,
    assess_budget: CallBudget | None = None,
    settings: Settings | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """Build the API with injected collaborators.

    Tests pass fakes for ``find_similar``, ``kimi_call`` and ``audit`` so
    nothing is retrieved, paid for or fetched. ``budget`` and
    ``assess_budget`` default to daily budgets sized by ``settings``
    (default: :meth:`Settings.from_env`).
    """
    cfg = settings or Settings.from_env()
    app = FastAPI(
        title="SAICA API",
        docs_url="/docs" if cfg.docs else None,
        redoc_url="/redoc" if cfg.docs else None,
        openapi_url="/openapi.json" if cfg.docs else None,
    )

    ask_budget = budget or DailyBudget(
        max_calls=cfg.ask_daily_calls, max_tokens_estimate=cfg.ask_daily_tokens
    )
    audits_budget = assess_budget or DailyBudget(max_calls=cfg.assess_daily_calls)
    ask_clients = PerClientLimit(cfg.ask_per_client_hour)
    assess_clients = PerClientLimit(cfg.assess_per_client_hour)
    ask_slots = Slots(cfg.ask_concurrency)
    assess_slots = Slots(cfg.assess_concurrency)
    ask_pool = ThreadPoolExecutor(cfg.ask_concurrency, thread_name_prefix="saica-ask")
    assess_pool = ThreadPoolExecutor(
        cfg.assess_concurrency, thread_name_prefix="saica-assess"
    )
    reports = DayCache(cfg.assess_cache_seconds, cfg.assess_cache_entries, clock=clock)
    # Refusals that will not change within minutes (no such repository, too
    # large, could not be read within limits), as ``(status, detail)``.
    refusals = DayCache(
        cfg.assess_negative_cache_seconds, cfg.assess_cache_entries, clock=clock
    )

    # Inner to outer: the guard (request id, body limit), then CORS.
    app.add_middleware(ApiGuard, max_body=MAX_BODY_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["content-type"],
        expose_headers=["x-request-id"],
    )

    # -- errors: our own text, a request id, never the input ------------------

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            {"detail": exc.detail, "request_id": _request_id(request)},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
            for err in exc.errors()
        ]
        first = errors[0] if errors else {"loc": [], "msg": "invalid request"}
        where = ".".join(p for p in first["loc"] if p != "body") or "body"
        return JSONResponse(
            {
                "detail": f"The request could not be read ({where}: {first['msg']}).",
                "errors": errors,
                "request_id": _request_id(request),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.error("request %s failed", _request_id(request), exc_info=exc)
        return JSONResponse(
            {"detail": GENERIC_ERROR, "request_id": _request_id(request)},
            status_code=500,
        )

    def caller(request: Request) -> str:
        return client_key(
            request.scope.get("client"),
            request.headers.getlist("x-forwarded-for"),
            cfg.trusted_proxy_hops,
            cfg.trusted_proxies,
        )

    async def run_bounded(pool: ThreadPoolExecutor, slots: Slots, timeout: float, fn):
        """Run ``fn`` in ``pool``. The caller holds a slot; the worker thread
        frees it when it ends, not when we stop waiting for it. A call that
        ran past ``timeout`` therefore keeps its slot until it really stops."""

        def guarded():
            try:
                return fn()
            finally:
                slots.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(pool, guarded)
        except BaseException:
            slots.release()  # the work never started
            raise
        # If nobody waits any more (timeout), do not warn about its error.
        future.add_done_callback(lambda f: f.cancelled() or f.exception())
        return await asyncio.wait_for(asyncio.shield(future), timeout)

    # -- routes ---------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, bool]:
        # No counters here: how much budget is left is nobody's business.
        return {"ok": True}

    @app.post("/ask", response_model=Answer)
    async def ask(q: Question, request: Request) -> Answer:
        question = q.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be blank")
        rid = _request_id(request)

        # Cheap refusals first; nothing below runs for a refused call.
        if not ask_clients.allow(caller(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many questions from this address. Please try again in an hour.",
                headers={"Retry-After": "3600"},
            )
        if not ask_slots.try_acquire():
            raise HTTPException(
                status_code=429, detail=BUSY, headers={"Retry-After": "5"}
            )
        try:
            ask_budget.reserve()
        except CostCapExceeded:
            ask_slots.release()
            raise HTTPException(
                status_code=429,
                detail="The question budget for today is used up. Please try again tomorrow.",
            ) from None

        run = _AskRun()

        def work() -> tuple[str, Any]:
            # Budget bookkeeping happens here, in the worker, so that it is
            # also right when the handler has stopped waiting (504).
            try:
                hits = hybrid_retrieve(question, k, find_similar=find_similar)
                run.nodes = hydrate(hits)
                prompt = build_prompt(question, run.nodes)
            except BaseException:
                ask_budget.release()  # nothing was sent to the model
                raise
            run.model_called = True
            answer_text, raw = kimi_call(prompt)
            run.tokens = _extract_total_tokens(raw)
            ask_budget.record(tokens=run.tokens)  # paid for, whoever still waits
            return answer_text, raw

        try:
            answer_text, raw = await run_bounded(
                ask_pool, ask_slots, cfg.ask_wall_clock, work
            )
        except asyncio.TimeoutError:
            log.error("request %s: ask ran past %.0f s", rid, cfg.ask_wall_clock)
            raise HTTPException(status_code=504, detail=GENERIC_ERROR) from None
        except Exception:  # noqa: BLE001 - logged here, generic text to the client
            log.exception(
                "request %s: %s failed",
                rid,
                "model call" if run.model_called else "retrieval",
            )
            raise HTTPException(status_code=500, detail=GENERIC_ERROR) from None

        return Answer(
            answer=answer_text,
            citations=[_node_to_citation(n) for n in run.nodes],
            kimi_tokens_used=run.tokens,
            model=_raw_model_name(raw),
        )

    @app.post("/assess")
    async def assess(req: AssessRequest, request: Request) -> JSONResponse:
        """Audit one public GitHub repository; returns an ``AuditReport``."""
        try:
            owner, repo = parse_repo_url(req.repo_url)
        except ValueError as exc:
            # parse_repo_url's own two sentences; nothing of the input.
            raise HTTPException(status_code=400, detail=str(exc)) from None
        rid = _request_id(request)
        key = f"{owner}/{repo}".lower()

        cached = reports.get(key)
        if cached is not None:
            return JSONResponse(cached, headers={"x-saica-cache": "hit"})
        refused = refusals.get(key)
        if refused is not None:
            raise HTTPException(
                status_code=refused[0],
                detail=refused[1],
                headers={"x-saica-cache": "hit"},
            )

        if not assess_clients.allow(caller(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many audits from this address. Please try again in an hour.",
                headers={"Retry-After": "3600"},
            )
        if not assess_slots.try_acquire():
            raise HTTPException(
                status_code=429, detail=BUSY, headers={"Retry-After": "5"}
            )
        try:
            audits_budget.reserve()
        except CostCapExceeded:
            assess_slots.release()
            raise HTTPException(
                status_code=429,
                detail="The audit budget for today is used up. Please try again tomorrow.",
            ) from None

        def work() -> dict:
            # The worker stores its own outcome: a result that arrives after
            # the handler gave up (504) is kept, not thrown away.
            try:
                report = audit(f"https://github.com/{owner}/{repo}")
                payload = report.model_dump(mode="json")
            except (RepoNotFound, ValueError) as exc:
                # No such repository: nothing was audited, give the call back.
                audits_budget.release()
                refusals.put(
                    key,
                    (
                        (404, str(exc))
                        if isinstance(exc, RepoNotFound)
                        else (400, BAD_REPO_URL)
                    ),
                )
                raise
            except (RepoTooLarge, DetectionAborted) as exc:
                refusals.put(key, (422, str(exc)))
                raise
            reports.put(key, payload)
            return payload

        try:
            payload = await run_bounded(
                assess_pool, assess_slots, cfg.assess_wall_clock, work
            )
        except asyncio.TimeoutError:
            log.error("request %s: audit of %s ran past the time limit", rid, key)
            raise HTTPException(
                status_code=504, detail="The audit took too long and was stopped."
            ) from None
        except ValueError:
            # Whatever the text says, the client gets the fixed sentence.
            raise HTTPException(status_code=400, detail=BAD_REPO_URL) from None
        except RepoNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (RepoTooLarge, DetectionAborted) as exc:
            log.warning("request %s: audit of %s: %s", rid, key, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except FetchUnavailable as exc:
            log.warning("request %s: audit of %s: %s", rid, key, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except AuditError as exc:
            log.warning("request %s: audit of %s: %s", rid, key, exc)
            raise HTTPException(status_code=502, detail=GENERIC_ERROR) from None
        except Exception:  # noqa: BLE001 - logged here, generic text to the client
            log.exception("request %s: audit of %s failed", rid, key)
            raise HTTPException(status_code=500, detail=GENERIC_ERROR) from None

        return JSONResponse(payload, headers={"x-saica-cache": "miss"})

    return app


def _extract_total_tokens(raw: Any) -> int:
    usage = getattr(raw, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, "total_tokens", 0) or 0)


def _raw_model_name(raw: Any) -> str:
    return str(getattr(raw, "model", "") or os.environ.get("AZURE_KIMI_MODEL", ""))


def _node_to_citation(n: NodeContext) -> Citation:
    return Citation(
        id=n.id,
        type=n.type,
        name=n.name,
        snippet=n.snippet,
        similarity=n.similarity,
        url=n.url,
    )


def main(argv: list[str] | None = None) -> None:
    """``python -m pipeline.ask.server`` runs the one server entry point,
    :func:`pipeline.webapp.main` (routes under ``/api``; ``--help`` prints
    help and exits)."""
    from pipeline.webapp import main as web_main

    web_main(argv)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
