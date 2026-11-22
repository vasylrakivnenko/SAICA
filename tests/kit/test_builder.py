"""Tests for what decides the kit's advertised numbers (review issue I8; evidence KT-01..04, KT-11, KT-12, KT-14).

  - the generated files are what the one generator writes (`bench/kitbuilder/build_kit.py --check`);
  - every draft entry parses, runs the benchmark's rule (programs) or says that it does not, and holds no
    comment, `{files}` or placeholder;
  - the pick rule of the page script (run under node) is the rule of the generator, for the default and for
    every limit the page offers;
  - the default kit and each constraint run on a fixture repository with a fake model and fake programs.
No network beyond 127.0.0.1, no paid call.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "site" / "public" / "kit"
KIT_JSON = REPO / "site" / "public" / "bench" / "kit.json"
PAGE = REPO / "site" / "src" / "components" / "KitBuilder.astro"
HARNESS = Path(__file__).resolve().parent / "kb_harness.mjs"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


sc = _load("saica_check_builder", KIT / "saica_check.py")
selftest = _load("saica_selftest_builder", KIT / "selftest.py")
bk = _load("saica_build_kit", REPO / "bench" / "kitbuilder" / "build_kit.py")
kit = json.loads(KIT_JSON.read_text())
BENCH_MODES = [m for m in kit["modes"] if m.get("benchmarked")]
CHECKS = [(m, r) for m in BENCH_MODES for r in m["rows"] if r.get("kit_check")]
SETTINGS = [
    {"type": t, "local": loc, "maxCost": cost, "pairs": pairs}
    for t, loc, cost, pairs in itertools.product(
        ["any", "program", "hybrid", "llm"],
        [False, True],
        ["inf", "0", "0.5", "1", "5"],
        [False, True],
    )
]


def py_picks(setting):
    cost = None if setting["maxCost"] == "inf" else float(setting["maxCost"])
    return {
        m["id"]: bk.choose(m, kit["floor"], setting["type"], setting["local"], cost)
        for m in kit["modes"]
    }


def py_config(setting):
    tools = []
    for m in kit["modes"]:
        c = py_picks(setting)[m["id"]]
        if c["kind"] == "pick":
            tools.append(
                next(r for r in m["rows"] if r["key"] == c["key"])["kit_check"]["entry"]
            )
    return {
        "version": 1,
        "kit": "custom",
        "builtin": {"enabled": True, "blocking": False},
        "tools": tools,
    }


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------


def test_generated_files_match_the_generator():
    """kit.json, recipes.json, the prompts, pairs.json, checks.example.json and SHA256SUMS are never hand-edited."""
    texts, _warnings = bk.build()
    stale = [
        str(p.relative_to(REPO))
        for p, text in texts.items()
        if not p.exists() or p.read_text() != text
    ]
    assert stale == [], "run: python bench/kitbuilder/build_kit.py"
    assert len(texts) == 17


def test_sha256sums_cover_the_kit_files():
    listed = dict(
        reversed(line.split("  ", 1))
        for line in (KIT / "SHA256SUMS").read_text().splitlines()
    )
    shipped = {
        str(p.relative_to(KIT))
        for p in KIT.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert set(listed) == shipped - {"SHA256SUMS"}
    for name, digest in listed.items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == digest, name


def test_kit_json_keeps_what_other_readers_need():
    assert (
        isinstance(kit["floor"], float) and 0 < kit["floor"] < 1
    )  # read by pipeline/maturity/evidence.py
    for m in kit["modes"]:
        assert m["id"] and m["fm"] in sc.FAILURE_MODES
        for r in m.get("rows", []):
            assert (
                r["key"] and r["short"] and r["category"]
            )  # read by the failure-mode pages
    assert len(BENCH_MODES) == 9 and len(kit["modes"]) == 11
    assert {b["id"] for b in kit["builtins"]} == {tid for tid, _fm in sc.BUILTIN_CHECKS}
    assert all(
        b["benchmarked"] is False and b["counts_as_coverage"] is False
        for b in kit["builtins"]
    )
    assert (
        kit["defaults"]["pairs"] is False
    )  # "use a measured pair" is off unless the user turns it on
    assert all(
        "cheaper_pair" not in m for m in kit["modes"]
    )  # AND / cascade numbers are not installable


# ---------------------------------------------------------------------------
# Every entry the builder can write
# ---------------------------------------------------------------------------


def test_every_reviewer_row_has_a_kit_check_or_a_reason():
    for m in BENCH_MODES:
        for r in m["rows"]:
            if (
                r["recommendable"]
                and r["ranked"] is not False
                and r["category"] in ("llm", "program", "hybrid")
            ):
                assert r["kit_check"], (m["id"], r["key"])
            else:
                assert r["kit_check"] is None, (m["id"], r["key"])
        ids = [r["kit_check"]["entry"]["id"] for r in m["rows"] if r.get("kit_check")]
        assert len(ids) == len(set(ids)), m["id"]


@pytest.mark.parametrize(
    "m, r", CHECKS, ids=[f"{m['id']}/{r['key']}" for m, r in CHECKS]
)
def test_entry_is_valid_and_safe(m, r):
    k = r["kit_check"]
    entry = k["entry"]
    cfg = sc.parse_config({"version": 1, "tools": [entry]})  # the draft parses
    assert cfg["tools"][0]["blocking"] is False
    assert "Benchmark J" in entry["note"]
    assert (
        f"{r['n_pos']} bad + {r['n_neg']} clean samples" in entry["note"]
    )  # n is shown
    assert "95% interval" in entry["note"]
    if not k["runs"]:
        # a tool the kit cannot run: listed, not runnable, and labelled
        assert entry["runs_per_commit"] is False and "command" not in entry
        assert (
            k["label"] == kit["labels"]["not_installed"] and k["label"] in entry["note"]
        )
        assert k["as_measured"] is False
        return
    cmd = entry["command"]
    assert "{files}" not in cmd and "{files_from}" not in cmd
    assert sc.placeholder_problem(cmd) is None
    assert "#" not in cmd and "\n" not in cmd  # no comment in a command (KT-04)
    assert (
        selftest._PLACEHOLDER_RE.search(cmd) is None
    )  # no <placeholder> marked runnable (KT-05)
    assert "--exit-zero" not in cmd  # a command that can never flag (KT-01)
    argv = shlex.split(cmd)
    assert argv[0] == "python3" and argv[1] in (
        ".saica/saica_llm_review.py",
        ".saica/saica_static.py",
    )
    recipe = r["recipe"]
    if r["category"] == "program":
        assert argv[1] == ".saica/saica_static.py" and "--added-lines-only" in argv
        assert k["as_measured"] is True and k["label"] is None
        codes = (recipe.get("config") or {}).get("counted_codes") or (
            recipe.get("config") or {}
        ).get("counted_rules")
        if codes:  # the counted codes are the recipe's, not typed again
            assert argv[argv.index("--codes") + 1] == ",".join(codes)
        else:
            assert "--codes" not in argv
        for arg in argv:
            if arg.startswith(
                "--tool-arg="
            ):  # every option comes from the benchmark's own command
                option = arg[len("--tool-arg=") :].split("=")[0]
                bench_cmd = recipe["command"].replace("-s B101", "--skip=B101")
                assert option in bench_cmd, (option, recipe["command"])
    else:
        assert argv[1] == ".saica/saica_llm_review.py"
        prompt = argv[argv.index("--prompt") + 1]
        assert (
            prompt == f".saica/prompts/{m['fm']}.md"
            and (KIT / "prompts" / f"{m['fm']}.md").is_file()
        )
        assert argv[argv.index("--model") + 1] == recipe["model"]
        assert ("--temperature" in argv) == (recipe.get("temperature") is not None)
        assert argv[argv.index("--api-key-env") + 1] == k["env"]["key"]
        status = k["unit"]["status"]
        assert (k["label"] is None) == (status in ("same", "adapter"))
        assert k["as_measured"] is (k["label"] is None)
        if k["label"]:
            assert k["label"] in entry["note"]
        assert (
            k["unit"]["benchmark"] in entry["note"]
            and k["unit"]["commit"] in entry["note"]
        )
        assert int(argv[argv.index("--timeout") + 1]) < entry["timeout_s"]


def test_modes_whose_benchmark_input_is_missing_at_commit_time_are_marked():
    status = {m["id"]: m["units"]["llm"]["status"] for m in BENCH_MODES}
    assert (
        status["test-manipulation"] == "not_available"
        and status["logic_error"] == "not_available"
    )
    assert status["fabrication"] == "adapter" and status["obsolescence"] == "adapter"
    assert (
        status["scope_creep"] == status["supply_chain"] == status["security"] == "same"
    )
    assert status["incomplete_execution"] == status["dependency_blindness"] == "partial"


# ---------------------------------------------------------------------------
# The pick rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setting", SETTINGS, ids=lambda s: "-".join(str(v) for v in s.values())
)
def test_pick_rule(setting):
    picks = py_picks(setting)
    for m in BENCH_MODES:
        c = picks[m["id"]]
        rows = {r["key"]: r for r in m["rows"]}
        if not m["reliable"]:
            assert c["kind"] == "unreliable"  # below the floor nothing is picked
            continue
        if c["kind"] != "pick":
            continue
        pick, best = rows[c["key"]], rows[c["best"]]
        assert pick["recommendable"] and pick["ranked"] is not False
        assert pick["j"] >= kit["floor"]
        # the pick cannot be told apart from the best check that fits
        assert pick["key"] in m["top_group"] or pick["j"] >= best["j_ci"][0]
        tied = [rows[k] for k in c["tied"]]
        runnable = [r for r in tied if r["kit_check"]["runs"]]
        if runnable:  # of those, the cheapest one the kit can run
            assert pick["kit_check"]["runs"] and pick["cost1k"] == min(
                r["cost1k"] for r in runnable
            )
    assert sc.parse_config(
        py_config(setting)
    )  # the whole draft parses (no duplicate ids)


def test_default_kit_and_example_config():
    default = py_picks(
        {"type": "any", "local": False, "maxCost": "inf", "pairs": False}
    )
    want = [
        {"mode": m["id"], "fm": m["fm"], "key": default[m["id"]]["key"]}
        for m in BENCH_MODES
        if default[m["id"]]["kind"] == "pick"
    ]
    assert kit["default_kit"] == want and want
    example = json.loads((KIT / "checks.example.json").read_text())
    cfg = sc.load_config(KIT / "checks.example.json")
    assert [t["id"] for t in example["tools"]] == [
        next(r for r in m["rows"] if r["key"] == p["key"])["kit_check"]["entry"]["id"]
        for p in want
        for m in BENCH_MODES
        if m["id"] == p["mode"]
    ]
    assert all(
        t["blocking"] is False for t in cfg["tools"]
    )  # nothing in the example blocks a commit
    assert cfg["builtin"] == {
        "enabled": True,
        "blocking": False,
        "tamper_blocking": True,
    }
    for t in example["tools"]:
        assert t["note"].startswith("Benchmark J ")  # measured, with its numbers
    # every example entry is a row of the results that may be recommended
    allowed = {r["kit_check"]["entry"]["id"] for _m, r in CHECKS}
    assert {t["id"] for t in example["tools"]} <= allowed


def test_page_script_agrees_with_the_generator():
    """The real inline script of KitBuilder.astro, run under node, for every limit the page offers."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    r = subprocess.run(
        [node, str(HARNESS), str(PAGE), str(KIT_JSON)],
        input=json.dumps(SETTINGS),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert len(out) == len(SETTINGS)
    for setting, res in zip(SETTINGS, out):
        want = py_picks(setting)
        for m in kit["modes"]:
            got = res["picks"][m["id"]]
            assert got["kind"] == want[m["id"]]["kind"], (setting, m["id"])
            assert got["key"] == want[m["id"]].get("key"), (setting, m["id"])
            if got["pair"]:
                assert (
                    setting["pairs"]
                    and m.get("pair")
                    and got["pair"] == [m["pair"]["a"], m["pair"]["b"]]
                )
        cfg = res["checks"]
        if not any(p["pair"] for p in res["picks"].values()):
            assert cfg == py_config(setting)
        sc.parse_config(cfg)
        prompt = res["prompt"]
        assert "Measured:" not in prompt  # the old wording
        assert "```json" in prompt and "SHA256SUMS" in prompt and "CODEOWNERS" in prompt
        assert "heuristics, not benchmarked" in prompt
        for t in cfg["tools"]:
            assert t["id"] in prompt
        n_runnable = sum(1 for t in cfg["tools"] if t["runs_per_commit"])
        if cfg["tools"]:
            assert "Benchmark J" in prompt
        if n_runnable:
            assert "At commit time this check sees" in prompt
        if len(cfg["tools"]) > n_runnable:
            assert "benchmark rule, not the installed check" in prompt
        assert ("estimate under independence, not measured" in res["union"]) == (
            n_runnable > 1
        )
    default = out[
        SETTINGS.index(
            {"type": "any", "local": False, "maxCost": "inf", "pairs": False}
        )
    ]
    assert (
        default["checks"]["tools"]
        == json.loads((KIT / "checks.example.json").read_text())["tools"]
    )


def test_page_text_has_the_new_wording():
    page = PAGE.read_text()
    assert (
        "Measured: J" not in page
        and "exact model, prompt and settings we measured" not in page
    )
    assert "kb-combined" not in page  # the combined prompt was never run: not offered
    assert 'id="kb-pairs" checked' not in page  # pairs are off by default
    assert "benchmark command: adapt paths" not in page  # the comment that held {files}


# ---------------------------------------------------------------------------
# The kits on a fixture repository
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def llm():
    """Flags a prompt that holds FLAG_ME, with the verdict field the prompt asks for."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(
                    "utf-8"
                )
            )
            prompt = body["messages"][0]["content"]
            seen.append(body)
            fields = re.findall(r'"([a-z_]+)"\s*:\s*true\s*(?:or|\|)\s*false', prompt)
            answer = json.dumps(
                {
                    fields[-1] if fields else "flag": "FLAG_ME" in prompt,
                    "evidence": "fixture",
                }
            )
            payload = {
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}]
            }
            if body.get("stream"):
                data = (
                    "data: %s\n\ndata: [DONE]\n\n"
                    % json.dumps(
                        {
                            "choices": [
                                {"delta": {"content": answer}, "finish_reason": "stop"}
                            ]
                        }
                    )
                ).encode()
                ctype = "text/event-stream"
            else:
                data, ctype = json.dumps(payload).encode(), "application/json"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.seen = seen
    yield server
    server.shutdown()
    server.server_close()


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


FIXTURE_SETTINGS = [
    {
        "type": "any",
        "local": False,
        "maxCost": "inf",
        "pairs": False,
    },  # the default kit
    {"type": "program", "local": False, "maxCost": "inf", "pairs": False},
    {"type": "llm", "local": False, "maxCost": "inf", "pairs": False},
    {"type": "hybrid", "local": False, "maxCost": "inf", "pairs": False},
    {"type": "any", "local": True, "maxCost": "inf", "pairs": False},
    {"type": "any", "local": False, "maxCost": "0", "pairs": False},
    {"type": "any", "local": False, "maxCost": "0.5", "pairs": False},
    {"type": "any", "local": False, "maxCost": "1", "pairs": False},
]


@pytest.mark.parametrize(
    "setting", FIXTURE_SETTINGS, ids=lambda s: "-".join(str(v) for v in s.values())
)
def test_kit_runs_on_a_fixture_repository(setting, tmp_path, llm):
    config = py_config(setting)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "SAICA_"))}
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name, out in (
        ("pyright", '{"generalDiagnostics": []}'),
        ("mypy", ""),
        ("ruff", "[]"),
    ):
        (fakebin / name).write_text("#!/bin/sh\nprintf '%%s' '%s'\n" % out)
        (fakebin / name).chmod(0o755)
    (fakebin / "python3").symlink_to(sys.executable)
    env.update(
        HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(home / ".gitconfig"),
        PATH=str(fakebin) + os.pathsep + env["PATH"], NO_PROXY="127.0.0.1", no_proxy="127.0.0.1",
        SAICA_CACHE_DIR=str(tmp_path / "cache"),
    )  # fmt: skip
    base = "http://127.0.0.1:%d/v1" % llm.server_address[1]
    for _m, r in CHECKS:
        if r["kit_check"]["env"]:
            env[r["kit_check"]["env"]["base"]] = base
            env[r["kit_check"]["env"]["key"]] = "sk-fixture-0123456789"
    repo = tmp_path / "repo"
    saica = repo / ".saica"
    (saica / "prompts").mkdir(parents=True)

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "commit.gpgsign", "false")
    for name in ("saica_check.py", "saica_llm_review.py", "saica_static.py"):
        shutil.copy2(str(KIT / name), str(saica / name))
    for p in (KIT / "prompts").glob("*"):
        shutil.copy2(str(p), str(saica / "prompts" / p.name))
    (saica / "checks.json").write_text(json.dumps(config, indent=2))
    (repo / ".gitignore").write_text(
        ".saica/events.jsonl\n.saica/pending.jsonl\n.saica/task.md\n.saica/session.txt\n.saica/final_message.txt\n"
    )
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base with the kit")

    def run():
        r = subprocess.run(
            [sys.executable, "-B", ".saica/saica_check.py", "run", "--staged"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert r.returncode == 0, r.stderr  # nothing in a generated kit blocks
        events = [
            json.loads(ln) for ln in (saica / "pending.jsonl").read_text().splitlines()
        ]
        assert all(selftest.validate_event(e) == [] for e in events)
        return {
            e["tool_id"]: e
            for e in events
            if e["tool_id"] and not e["tool_id"].startswith("saica:")
        }, events

    # 1. a clean change, with everything the checks need
    (repo / "app.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    (repo / "util.py").write_text("def twice(x):\n    return 2 * x\n")
    (saica / "task.md").write_text("Add sub() and a twice() helper.\n")
    (saica / "session.txt").write_text("[1] USER: add sub()\n[2] ASSISTANT: done\n")
    (saica / "final_message.txt").write_text("Added sub() and twice(); tests pass.\n")
    git("add", "-A")
    by, events = run()
    assert set(by) == {t["id"] for t in config["tools"]}
    for t in config["tools"]:
        e = by[t["id"]]
        if not t["runs_per_commit"]:
            assert e["outcome"] == "not_runnable"  # hybrid tools: listed, not run
        else:
            assert e["outcome"] == "pass", (t["id"], e["detail"])
            assert e["detail"].startswith("ok:")
    # a mode counts as covered only through a runnable configured tool
    covered = {
        fm for t in config["tools"] if t["runs_per_commit"] for fm in t["failure_modes"]
    }
    not_covered = {e["failure_mode"] for e in events if e["outcome"] == "not_covered"}
    assert not_covered == set(sc.FAILURE_MODES) - covered

    # 2. the same change with a planted problem: LLM entries catch it, programs keep the benchmark rule
    (repo / "util.py").write_text("def twice(x):\n    return 2 * x  # FLAG_ME\n")
    (saica / "session.txt").write_text(
        "[1] USER: add sub()\n[2] TOOL CALL Edit: tests/test_app.py FLAG_ME\n"
    )
    git("add", "-A")
    by, _events = run()
    for t in config["tools"]:
        if not t["runs_per_commit"]:
            continue
        e = by[t["id"]]
        if "saica_llm_review.py" in t["command"]:
            assert e["outcome"] == "caught" and e["detail"].startswith("flagged:"), (
                t["id"],
                e["detail"],
            )
        else:
            assert e["outcome"] == "pass"  # the fake checker reports nothing

    # 3. without the files a prompt needs, its check is an error, never a pass
    (saica / "session.txt").unlink()
    (saica / "final_message.txt").unlink()
    by, _events = run()
    for t in config["tools"]:
        if t["runs_per_commit"] and "--fill" in t["command"]:
            assert by[t["id"]]["outcome"] == "error", t["id"]
            assert "--fill file not found" in by[t["id"]]["detail"]
