#!/usr/bin/env python3
"""SAICA supervision kit: run a SAICA-Bench LLM reviewer prompt as a per-commit check.

Fills a reviewer prompt template with the change being committed and the task
text, sends it to an OpenAI-compatible chat-completions endpoint, parses the
JSON verdict the way SAICA-Bench does, and prints ONE result line on stdout:

    flagged: <evidence>        exit 1    saica_check.py records `caught`
    ok: <reason>               exit 0    saica_check.py records `pass`
    error: <what went wrong>   exit 127  saica_check.py records `error`

Errors use exit 127 because contract v1 maps only exit 127 and timeouts to
``error``; any other non-zero exit is recorded as ``caught`` and could block a
commit. ``--error-exit N`` picks another code for use outside the kit runner.

Python 3.9+, standard library only. Copy to ``.saica/saica_llm_review.py`` and
call it from a ``command`` in ``.saica/checks.json``; see the kit README,
section "LLM reviewer checks".

Which change is reviewed:
  --diff-file PATH   a unified diff file (``-`` = stdin)
  --staged           ``git diff --cached``. Inside ``saica_check.py run --staged``
                     git is pointed at the snapshot's temporary index, so this is
                     exactly the change being committed.
  --commit REV       REV against its first parent (the empty tree for a root commit)
  (default)          --staged when SAICA_REPO_ROOT is set (saica_check's pre-commit
                     temporary checkout), otherwise --commit HEAD (CI, ``run --commit``,
                     manual runs).

Template placeholders (``{name}``; write literal braces as ``{{`` / ``}}`` as in
Python's str.format, so the benchmark prompts can be used verbatim):
  {issue} {task} {spec}    task text: --task-file, else $SAICA_TASK_FILE, else
                           .saica/task.md, else "(no task description provided)"
  {patch} {diff} {code}    the diff
  {context}                --context-file files, formatted as in SAICA-Bench
  --fill NAME=FILE         any other placeholder
Unknown placeholders are left empty with a warning. For a Markdown prompt file
the template is the first fenced code block.

Several --prompt files run in an UNTESTED combined mode: one request holding
every template, answered with one JSON object keyed by failure mode (the file
name stem); one result line per mode; exit 1 if any mode flagged, else the
error code if any answer was unreadable, else 0.

The API base URL and key are read from the environment variables named by
--api-base-env / --api-key-env; the key is never printed.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

EXIT_OK = 0
EXIT_FLAGGED = 1
DEFAULT_ERROR_EXIT = 127
NO_TASK = "(no task description provided)"
DEFAULT_TASK_FILE = ".saica/task.md"
DEFAULT_MAX_TASK_CHARS = 20000  # SAICA-Bench cut issue text at 15k-20k characters
CONTEXT_MAX_CHARS = 15000  # SAICA-Bench: content[:15000] per context file
DEFAULT_MAX_DIFF_CHARS = 100000
DEFAULT_MAX_TOKENS = 16384  # SAICA-Bench default answer budget
DEFAULT_TIMEOUT_S = 240.0  # keep below the checks.json timeout_s (default 300)
RESULT_MAX = 300
COMBINED_WARNING = "combined review is not benchmarked; SAICA-Bench scores apply to one prompt per call"

TASK_KEYS = ("issue", "task", "spec")
DIFF_KEYS = ("patch", "diff", "code")
EVIDENCE_KEYS = ("evidence", "reason", "explanation", "rationale")
_DIFF_ARGS = [
    "diff",
    "--no-color",
    "--no-ext-diff",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


class ReviewError(Exception):
    """A failure that is reported as ``error: ...`` with the error exit code."""


# ---------------------------------------------------------------------------
# Output (every line passes through the key redactor)
# ---------------------------------------------------------------------------


class _Redactor:
    def __init__(self) -> None:
        self.secrets: List[str] = []

    def add(self, secret: Optional[str]) -> None:
        if not secret or len(secret) < 4:
            return
        for s in (secret, urllib.parse.quote(secret, safe="")):
            if s not in self.secrets:
                self.secrets.append(s)
        self.secrets.sort(key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return text


REDACT = _Redactor()


def one_line(text: object, limit: int = RESULT_MAX) -> str:
    s = " ".join(str(text).split())
    if len(s) > limit:
        s = s[: limit - 3].rstrip() + "..."
    return s


def say(line: str) -> None:
    sys.stdout.write(REDACT(line) + "\n")
    sys.stdout.flush()


def warn(msg: str) -> None:
    sys.stderr.write(REDACT("saica-llm-review: warning: " + msg) + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Files and git
# ---------------------------------------------------------------------------


def _search_bases(prefer_repo_root: bool) -> List[Path]:
    cwd = Path.cwd()
    root = os.environ.get("SAICA_REPO_ROOT")
    if not root:
        return [cwd]
    return [Path(root), cwd] if prefer_repo_root else [cwd, Path(root)]


def find_file(name: str, prefer_repo_root: bool = False) -> Optional[Path]:
    """Resolve ``name``: absolute as is; relative against the current directory and
    $SAICA_REPO_ROOT (the real checkout during a pre-commit run)."""
    p = Path(name).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    for base in _search_bases(prefer_repo_root):
        if (base / p).is_file():
            return base / p
    return None


def read_text(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ReviewError("cannot read %s %s: %s" % (what, path, exc.strerror or exc))


def git(args: List[str], check: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise ReviewError("git is not installed or not on PATH")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise ReviewError("git %s failed: %s" % (args[0], one_line(err, 200)))
    return proc.stdout.decode("utf-8", "replace")


def staged_diff() -> str:
    return git(_DIFF_ARGS + ["--cached"])


def commit_diff(rev: str) -> str:
    sha = git(
        ["rev-parse", "--verify", "--quiet", rev + "^{commit}"], check=False
    ).strip()
    if not sha:
        raise ReviewError("not a commit: %s" % rev)
    parents = git(["rev-list", "--parents", "-n", "1", sha]).split()
    if len(parents) > 1:
        base = parents[1]
    else:
        shallow = git(["rev-parse", "--git-path", "shallow"], check=False).strip()
        if (
            shallow
            and Path(shallow).is_file()
            and sha in read_text(Path(shallow), "file").split()
        ):
            raise ReviewError(
                "%s has no parent in this shallow clone; fetch more history "
                "(actions/checkout: fetch-depth: 0)" % sha[:12]
            )
        base = git(["mktree"]).strip()  # this repository's empty tree
    return git(_DIFF_ARGS + [base, sha])


def obtain_diff(args: argparse.Namespace) -> Tuple[str, str]:
    if args.diff_file:
        if args.diff_file == "-":
            return sys.stdin.read(), "stdin"
        p = find_file(args.diff_file)
        if p is None:
            raise ReviewError("diff file not found: %s" % args.diff_file)
        return read_text(p, "diff file"), "diff file %s" % args.diff_file
    if args.staged or (args.commit is None and os.environ.get("SAICA_REPO_ROOT")):
        return staged_diff(), "staged changes"
    rev = args.commit or "HEAD"
    return commit_diff(rev), "commit %s" % rev


def load_task(args: argparse.Namespace) -> str:
    # The task file usually stays untracked, so the real checkout is searched first.
    spec = args.task_file or os.environ.get("SAICA_TASK_FILE") or ""
    if spec:
        p = find_file(spec, prefer_repo_root=True)
        if p is None:
            raise ReviewError("task file not found: %s" % spec)
    else:
        p = find_file(DEFAULT_TASK_FILE, prefer_repo_root=True)
        if p is None:
            warn(
                "no task file (%s or $SAICA_TASK_FILE); the reviewer gets no task "
                "description" % DEFAULT_TASK_FILE
            )
            return NO_TASK
    text = read_text(p, "task file").strip()
    if not text:
        warn("task file %s is empty" % p)
        return NO_TASK
    if args.max_task_chars and len(text) > args.max_task_chars:
        warn("task text cut to %d characters (--max-task-chars)" % args.max_task_chars)
        text = text[: args.max_task_chars]
    return text


def load_context(specs: List[str]) -> str:
    parts = []
    for spec in specs:
        p = find_file(spec)
        if p is None:
            warn("context file not found, skipped: %s" % spec)
            continue
        content = read_text(p, "context file")[:CONTEXT_MAX_CHARS]
        parts.append(
            "\nRepository file (not changed by the patch): %s\n<file>\n%s\n</file>\n"
            % (spec, content)
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_FENCE_OPEN_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FLAG_SPEC_RE = re.compile(
    r"\"([A-Za-z_][\w-]*)\"\s*:\s*<?\s*(?:true|false)\s*(?:or|\||/)\s*(?:true|false)",
    re.I,
)


def first_fenced_block(text: str) -> Optional[str]:
    """Content of the first ``` / ~~~ fenced block (CommonMark rules), or None."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    for i, line in enumerate(lines):
        m = _FENCE_OPEN_RE.match(line)
        if not m or (m.group(2)[0] == "`" and "`" in m.group(3)):
            continue
        indent, fence = len(m.group(1)), m.group(2)
        close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(fence[0]), len(fence)))
        body = []
        for inner in lines[i + 1 :]:
            if close.match(inner):
                break
            strip = min(indent, len(inner) - len(inner.lstrip(" ")))
            body.append(inner[strip:])
        return "\n".join(body)
    return None


class Prompt:
    def __init__(self, path: str, mode: str, template: str) -> None:
        self.path = path
        self.mode = mode
        self.template = template


def load_prompt(spec: str) -> Prompt:
    p = find_file(spec)
    if p is None:
        raise ReviewError("prompt file not found: %s" % spec)
    text = read_text(p, "prompt file")
    if p.suffix.lower() in (".md", ".markdown"):
        block = first_fenced_block(text)
        if block is None:
            warn("%s has no fenced code block; using the whole file" % spec)
        else:
            text = block
    if not text.strip():
        raise ReviewError("prompt template %s is empty" % spec)
    return Prompt(spec, p.stem, text)


def fill_template(template: str, values: Dict[str, str]) -> Tuple[str, List[str]]:
    """Replace ``{name}`` placeholders. ``{{`` / ``}}`` become literal braces when the
    template uses that escaping (it contains ``{{``); otherwise braces are left alone.
    """
    escapes = "{{" in template
    unknown: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name is None:
            return m.group(0)[0] if escapes else m.group(0)
        if name in values:
            return values[name]
        if name not in unknown:
            unknown.append(name)
        return ""

    return _TOKEN_RE.sub(repl, template), unknown


def detect_flag_field(template: str) -> Optional[str]:
    """The answer field the template asks to be true/false (last one wins)."""
    skeleton, _ = fill_template(template, {})
    found = _FLAG_SPEC_RE.findall(skeleton)
    return found[-1] if found else None


def build_combined(prompts: List[Prompt], filled: List[str]) -> str:
    modes = [p.mode for p in prompts]
    skeleton = "{" + ", ".join('"%s": {...}' % m for m in modes) + "}"
    parts = [
        "You are running %d independent reviews of the same change, one per failure "
        "mode. Each section below is a complete review task with its own question and "
        "its own JSON answer format. Judge every section on its own, as if it were the "
        "only one.\n\nAnswer with ONE JSON object only, keyed by failure mode; each value "
        "is the JSON object that section asks for:\n%s" % (len(modes), skeleton)
    ]
    for p, text in zip(prompts, filled):
        parts.append("## Failure mode: %s\n\n%s" % (p.mode, text.strip()))
    parts.append(
        "Final answer: ONE JSON object keyed by failure mode (%s); each value is that "
        "section's answer object." % ", ".join(modes)
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Answer parsing (as in SAICA-Bench: text after </think>, last JSON object)
# ---------------------------------------------------------------------------


def _after_think(text: str) -> str:
    return text.split("</think>")[-1]


def json_objects_from_end(text: str) -> Iterator[dict]:
    dec = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            obj, _end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def _first_bool_key(obj: dict) -> Optional[str]:
    for k, v in obj.items():
        if isinstance(v, bool):
            return k
    return None


def find_verdict(
    text: str, field: Optional[str]
) -> Tuple[Optional[dict], Optional[str]]:
    body = _after_think(text)
    for obj in json_objects_from_end(body):
        if field is None:
            key = _first_bool_key(obj)
            if key is not None:
                return obj, key
        elif field in obj:
            return obj, field
    if field:
        m = re.search(r"\"%s\"\s*:\s*(true|false)" % re.escape(field), body)
        if m:
            return {field: m.group(1) == "true", "evidence": "(partial parse)"}, field
    return None, field


def evidence_text(obj: dict, field: str) -> str:
    main, used = "", None
    for k in EVIDENCE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            main, used = v.strip(), k
            break
    extras = []
    for k, v in obj.items():
        if k in (field, used) or isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (str, int, float)) and str(v).strip():
            extras.append("%s=%s" % (k, v))
    if extras:
        main = (main + " " if main else "") + "(" + ", ".join(extras) + ")"
    return main


def judge(
    obj: Optional[dict], field: Optional[str], answer: str, finish: object
) -> Tuple[str, str]:
    """Return (status, text); status is flagged | ok | unreadable."""
    if obj is None or field is None:
        why = "no JSON verdict%s found in the answer" % (
            " with %r" % field if field else ""
        )
        if finish == "length":
            why += " (it stopped at the token limit; raise --max-tokens)"
        tail = one_line(_after_think(answer)[-160:], 160)
        return "unreadable", why + (": ...%s" % tail if tail else " (empty answer)")
    value = obj.get(field)
    if value is True:
        return (
            "flagged",
            evidence_text(obj, field) or "(no evidence given; %s=true)" % field,
        )
    if value is False:
        ev = evidence_text(obj, field)
        return "ok", "%s=false" % field + (" - " + ev if ev else "")
    return "unreadable", "%r is %s, not true/false" % (
        field,
        one_line(json.dumps(value), 60),
    )


def combined_verdicts(
    text: str, prompts: List[Prompt], fields: Dict[str, Optional[str]], finish: object
) -> List[Tuple[str, str, str]]:
    modes = [p.mode for p in prompts]
    top = None
    for obj in json_objects_from_end(_after_think(text)):
        if any(isinstance(obj.get(m), dict) for m in modes):
            top = obj
            break
    out = []
    for mode in modes:
        if top is None:
            status, msg = judge(None, fields[mode] or mode, text, finish)
            out.append((mode, status, msg))
            continue
        value = top.get(mode)
        if isinstance(value, bool):
            status, msg = judge({mode: value}, mode, text, finish)
        elif isinstance(value, dict):
            field = fields[mode]
            if field is None:
                field = mode if mode in value else _first_bool_key(value)
            status, msg = judge(value, field, text, finish)
        else:
            status, msg = (
                "unreadable",
                "no answer for %s in the combined JSON object" % mode,
            )
        out.append((mode, status, msg))
    return out


# ---------------------------------------------------------------------------
# HTTP (urllib; no redirects, loopback never proxied)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None  # a redirect would resend the key to another URL: fail instead


def endpoint_url(base: str, api_version: Optional[str]) -> str:
    parts = urllib.parse.urlsplit(base.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ReviewError("the API base URL must start with http:// or https://")
    path = parts.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if api_version and not any(k == "api-version" for k, _v in query):
        query.append(("api-version", api_version))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, urllib.parse.urlencode(query), "")
    )


def _ssl_context() -> ssl.SSLContext:
    """System trust store; if SSL_CERT_FILE is unset and certifi is installed, also trust its bundle.
    (python.org and uv-managed Pythons on macOS often ship without a usable system CA path.)
    """
    ctx = ssl.create_default_context()
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi  # optional; not required by the kit

            ctx.load_verify_locations(certifi.where())
        except (
            Exception
        ):  # noqa: BLE001 - certifi missing or unreadable: keep the system store
            pass
    return ctx


def _opener(host: str) -> urllib.request.OpenerDirector:
    handlers: list = [
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=_ssl_context()),
    ]
    if host.lower() in _LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(2000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - best effort only
        raw = ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raw = (
                err.get("message", json.dumps(err))
                if isinstance(err, dict)
                else str(err)
            )
    except ValueError:
        pass
    return one_line(raw or exc.reason, 200)


def collect_stream(resp, deadline: float) -> dict:  # type: ignore[no-untyped-def]
    """Assemble an SSE chat-completions stream into the non-streamed JSON shape."""
    parts: List[str] = []
    finish = None
    usage: dict = {}
    for raw in resp:  # binary line iteration splits on b"\n" only
        if time.monotonic() > deadline:
            raise ReviewError("timed out while reading the streamed answer")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("error"):
            raise ReviewError(
                "the API reported an error mid-stream: %s" % one_line(ev["error"], 200)
            )
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices") or []:
            delta = ch.get("delta") or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            finish = ch.get("finish_reason") or finish
    return {
        "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}],
        "usage": usage,
    }


def _read_response(resp, stream: bool, deadline: float) -> dict:  # type: ignore[no-untyped-def]
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" in ctype or (stream and "json" not in ctype):
        return collect_stream(resp, deadline)
    raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        raise ReviewError(
            "the API returned a non-JSON response: %s" % one_line(raw, 160)
        )


def call_model(args: argparse.Namespace, prompt: str, base: str, key: str) -> dict:
    url = endpoint_url(base, args.api_version)
    host = urllib.parse.urlsplit(url).netloc
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if args.stream else "application/json",
        "User-Agent": "saica-llm-review/1",
    }
    if key:
        if args.api_style == "azure":
            headers["api-key"] = key
        else:
            headers["Authorization"] = "Bearer " + key
    body: dict = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if args.max_tokens:
        field = "max_completion_tokens" if args.api_style == "azure" else "max_tokens"
        body[field] = args.max_tokens
    if args.temperature is not None:
        body["temperature"] = args.temperature
    if args.stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    body.update(args.extra_body)
    data = json.dumps(body).encode("utf-8")
    opener = _opener(urllib.parse.urlsplit(url).hostname or "")
    deadline = time.monotonic() + args.timeout
    last = ""
    attempts = 0
    for attempt in range(args.retries + 1):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        attempts += 1
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=remaining) as resp:
                return _read_response(resp, args.stream, deadline)
        except urllib.error.HTTPError as exc:
            detail = _http_error_text(exc)
            if exc.code == 400 and "content_filter" in detail.lower():
                raise ReviewError(
                    "the provider's content filter refused the prompt (HTTP 400)"
                )
            last = "HTTP %d from %s: %s" % (exc.code, host, detail)
            if exc.code != 429 and exc.code < 500:
                raise ReviewError(last)
        except (
            urllib.error.URLError,
            socket.timeout,
            http.client.HTTPException,
            OSError,
        ) as exc:
            reason = getattr(exc, "reason", None) or exc
            last = "%s: %s" % (host, one_line(reason, 160))
        if attempt < args.retries:
            pause = min(5.0 * (attempt + 1), deadline - time.monotonic() - 1)
            if pause > 0:
                time.sleep(pause)
    raise ReviewError(
        "model call failed after %d attempt(s) within %gs: %s"
        % (attempts, args.timeout, last or "no time left")
    )


def answer_of(resp: object) -> Tuple[str, object, object]:
    if not isinstance(resp, dict):
        raise ReviewError("unexpected API response (not a JSON object)")
    if resp.get("error"):
        raise ReviewError("API error: %s" % one_line(json.dumps(resp["error"]), 200))
    choices = resp.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ReviewError("the API response has no choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):  # content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    finish = choices[0].get("finish_reason")
    if finish == "content_filter" and not content:
        raise ReviewError("the provider's content filter withheld the answer")
    return content if isinstance(content, str) else "", finish, resp.get("usage")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    error_exit = DEFAULT_ERROR_EXIT

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        say("error: bad arguments: %s" % message)
        sys.exit(self.error_exit)


def _prescan_error_exit(argv: List[str]) -> int:
    for i, a in enumerate(argv):
        val = None
        if a == "--error-exit" and i + 1 < len(argv):
            val = argv[i + 1]
        elif a.startswith("--error-exit="):
            val = a.split("=", 1)[1]
        if val is not None:
            try:
                n = int(val)
            except ValueError:
                return DEFAULT_ERROR_EXIT
            return n if 0 <= n <= 255 and n != EXIT_FLAGGED else DEFAULT_ERROR_EXIT
    return DEFAULT_ERROR_EXIT


def build_parser() -> _Parser:
    p = _Parser(
        prog="saica_llm_review.py",
        description=(
            "Run a SAICA-Bench LLM reviewer prompt on the change being committed. "
            "Prints one line: 'flagged: ...' (exit 1), 'ok: ...' (exit 0) or "
            "'error: ...' (exit 127, which saica_check.py records as 'error')."
        ),
    )
    p.add_argument(
        "--prompt",
        action="append",
        required=True,
        metavar="PATH",
        help="prompt template (.md: first fenced code block; else the whole file). "
        "Repeat for the UNTESTED combined mode (one request, one line per mode)",
    )
    p.add_argument("--model", help="model / deployment id (required unless --dry-run)")
    p.add_argument(
        "--api-style",
        choices=("openai", "azure"),
        default="openai",
        help="openai: Authorization: Bearer + max_tokens; azure: api-key header + "
        "max_completion_tokens (default: openai)",
    )
    p.add_argument(
        "--api-base-env",
        default="SAICA_LLM_API_BASE",
        metavar="NAME",
        help="environment variable holding the API base URL, e.g. "
        "https://host/v1 (default: SAICA_LLM_API_BASE)",
    )
    p.add_argument(
        "--api-key-env",
        default="SAICA_LLM_API_KEY",
        metavar="NAME",
        help="environment variable holding the API key; '' sends no key "
        "(default: SAICA_LLM_API_KEY)",
    )
    p.add_argument(
        "--api-version",
        metavar="VER",
        help="add ?api-version=VER (classic Azure OpenAI deployment URLs)",
    )
    p.add_argument(
        "--temperature",
        type=float,
        help="sampling temperature (default: not sent, i.e. the provider default)",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        metavar="N",
        help="answer token budget; 0 = not sent (default: %d)" % DEFAULT_MAX_TOKENS,
    )
    p.add_argument(
        "--stream",
        action="store_true",
        help="stream the answer (needed for long answers behind proxies "
        "with ~100 s limits, e.g. Hyperbolic)",
    )
    p.add_argument(
        "--extra-body",
        default="{}",
        metavar="JSON",
        help='JSON object merged into the request, e.g. \'{"reasoning_effort": "low"}\'',
    )
    p.add_argument(
        "--flag-field",
        default="auto",
        metavar="NAME",
        help="answer field that means flagged (default auto: the field the template "
        "asks to be 'true or false', else the first boolean field)",
    )
    p.add_argument(
        "--task-file",
        metavar="PATH",
        help="task / issue text (default: $SAICA_TASK_FILE, else %s)"
        % DEFAULT_TASK_FILE,
    )
    p.add_argument(
        "--context-file",
        action="append",
        default=[],
        metavar="PATH",
        help="repository file shown to the reviewer as {context} (repeatable)",
    )
    p.add_argument(
        "--fill",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="fill placeholder {NAME} with the contents of PATH (repeatable)",
    )
    p.add_argument(
        "--max-diff-chars",
        type=int,
        default=DEFAULT_MAX_DIFF_CHARS,
        metavar="N",
        help="cut the diff after N characters; 0 = no limit (default: %d)"
        % DEFAULT_MAX_DIFF_CHARS,
    )
    p.add_argument(
        "--max-task-chars",
        type=int,
        default=DEFAULT_MAX_TASK_CHARS,
        metavar="N",
        help="cut the task text after N characters; 0 = no limit (default: %d)"
        % DEFAULT_MAX_TASK_CHARS,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--diff-file", metavar="PATH", help="review this unified diff (- = stdin)"
    )
    src.add_argument("--staged", action="store_true", help="review git diff --cached")
    src.add_argument(
        "--commit", metavar="REV", help="review REV against its first parent"
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="S",
        help="total seconds for the call including retries; keep it below the "
        "checks.json timeout_s (default: %g)" % DEFAULT_TIMEOUT_S,
    )
    p.add_argument(
        "--retries",
        type=int,
        default=2,
        metavar="N",
        help="retries on HTTP 429 / 5xx / connection errors (default: 2)",
    )
    p.add_argument(
        "--error-exit",
        type=int,
        default=DEFAULT_ERROR_EXIT,
        metavar="N",
        help="exit code for errors (default: 127, recorded as 'error' by "
        "saica_check.py; any other non-zero code is recorded as 'caught')",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the filled prompt and exit 0 without calling the API",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="report diff source, prompt size and token usage on stderr",
    )
    return p


def _check_args(p: _Parser, args: argparse.Namespace) -> None:
    if not args.dry_run and not args.model:
        p.error("--model is required (unless --dry-run)")
    if (
        args.timeout <= 0
        or args.retries < 0
        or args.max_diff_chars < 0
        or args.max_task_chars < 0
    ):
        p.error("--timeout must be > 0 and --retries / --max-*-chars >= 0")
    if not 0 <= args.error_exit <= 255 or args.error_exit == EXIT_FLAGGED:
        p.error("--error-exit must be 0 or 2..255 (1 means flagged)")
    try:
        extra = json.loads(args.extra_body)
    except ValueError as exc:
        p.error("--extra-body is not valid JSON: %s" % exc)
    if not isinstance(extra, dict):
        p.error("--extra-body must be a JSON object")
    args.extra_body = extra
    for item in args.fill:
        name, sep, _path = item.partition("=")
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            p.error("--fill expects NAME=PATH, got %r" % item)


def run(p: _Parser, args: argparse.Namespace) -> int:
    _check_args(p, args)
    key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    REDACT.add(key)

    prompts = [load_prompt(spec) for spec in args.prompt]
    modes = [pr.mode for pr in prompts]
    dupes = sorted({m for m in modes if modes.count(m) > 1})
    if dupes:
        raise ReviewError(
            "several prompt files share the mode name %s" % ", ".join(dupes)
        )
    combined = len(prompts) > 1
    if combined:
        warn(COMBINED_WARNING)

    diff, source = obtain_diff(args)
    if not diff.strip() and not args.dry_run:
        say("ok: no changes to review (%s)" % source)
        return EXIT_OK
    if args.max_diff_chars and len(diff) > args.max_diff_chars:
        warn(
            "diff has %d characters; only the first %d are reviewed (--max-diff-chars)"
            % (len(diff), args.max_diff_chars)
        )
        diff = diff[: args.max_diff_chars] + (
            "\n[diff truncated: %d of %d characters shown]\n"
            % (args.max_diff_chars, len(diff))
        )
    task = load_task(args)
    values: Dict[str, str] = {k: task for k in TASK_KEYS}
    values.update({k: diff for k in DIFF_KEYS})
    values["context"] = load_context(args.context_file)
    for item in args.fill:
        name, _sep, path = item.partition("=")
        fp = find_file(path)
        if fp is None:
            raise ReviewError("--fill file not found: %s" % path)
        values[name] = read_text(fp, "--fill file")

    filled = []
    for pr in prompts:
        text, unknown = fill_template(pr.template, values)
        if unknown:
            warn(
                "%s: unknown placeholder(s) left empty (use --fill NAME=FILE): %s"
                % (pr.path, ", ".join("{%s}" % u for u in unknown))
            )
        names = {m.group(1) for m in _TOKEN_RE.finditer(pr.template) if m.group(1)}
        if not names & set(DIFF_KEYS) and not any(
            f.partition("=")[0] in names for f in args.fill
        ):
            warn(
                "%s has no {patch} / {diff} / {code} placeholder: the change is not sent "
                "to the reviewer" % pr.path
            )
        filled.append(text)
    prompt = build_combined(prompts, filled) if combined else filled[0]
    fields = {
        pr.mode: (
            args.flag_field
            if args.flag_field != "auto"
            else detect_flag_field(pr.template)
        )
        for pr in prompts
    }

    if args.dry_run:
        sys.stdout.write(REDACT(prompt) + "\n")
        sys.stdout.flush()
        return EXIT_OK

    base = os.environ.get(args.api_base_env, "").strip()
    if not base:
        raise ReviewError(
            "environment variable %s (API base URL) is not set" % args.api_base_env
        )
    if args.api_key_env and not key:
        raise ReviewError(
            "environment variable %s (API key) is not set" % args.api_key_env
        )
    if args.verbose:
        warn(
            "reviewing %s: %d diff chars, %d prompt chars, model %s"
            % (source, len(diff), len(prompt), args.model)
        )
    resp = call_model(args, prompt, base, key)
    answer, finish, usage = answer_of(resp)
    if args.verbose:
        warn("finish_reason=%s usage=%s" % (finish, one_line(json.dumps(usage), 200)))

    if not combined:
        obj, field = find_verdict(answer, fields[prompts[0].mode])
        status, text = judge(obj, field, answer, finish)
        label = {"flagged": "flagged", "ok": "ok"}.get(
            status, "error: unreadable answer"
        )
        say("%s: %s" % (label, one_line(text)))
        return {"flagged": EXIT_FLAGGED, "ok": EXIT_OK}.get(status, args.error_exit)

    results = combined_verdicts(answer, prompts, fields, finish)
    for mode, status, text in results:
        label = {"flagged": "flagged", "ok": "ok"}.get(
            status, "error: unreadable answer"
        )
        say("%s %s: %s" % (mode, label, one_line(text, 200)))
    statuses = {s for _m, s, _t in results}
    if "flagged" in statuses:
        return EXIT_FLAGGED
    if "unreadable" in statuses:
        return args.error_exit
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    error_exit = _prescan_error_exit(argv)
    parser = build_parser()
    parser.error_exit = error_exit
    try:
        args = parser.parse_args(argv)
        if 0 <= args.error_exit <= 255 and args.error_exit != EXIT_FLAGGED:
            error_exit = args.error_exit
        return run(parser, args)
    except ReviewError as exc:
        say("error: %s" % one_line(exc))
        return error_exit
    except KeyboardInterrupt:
        say("error: interrupted")
        return error_exit
    except Exception as exc:  # noqa: BLE001 - a crash must not look like a finding
        say("error: internal error: %s: %s" % (type(exc).__name__, one_line(exc, 200)))
        return error_exit


if __name__ == "__main__":
    sys.exit(main())
