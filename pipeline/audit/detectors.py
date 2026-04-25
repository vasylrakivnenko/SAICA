"""Detection rules for the audit analyzer.

Each function takes a path to a checked-out repo root and returns the
relevant slice of the detected stack.  Detection is **conservative** —
we'd rather under-claim than tell a user they have a tool installed
when they don't.

Conventions:
  * Every returned ``DetectedTool`` resolves to a real KG id that exists
    in ``data/tools/``.  Tools detected by name but not present in the
    KG are returned with ``in_kg=False`` so they can be flagged for
    editorial review.
  * Each detection records the file paths (relative to repo root) that
    triggered it.  The UI renders these as "we detected X because we
    saw Y".
  * ``confidence`` follows the roadmap convention:
      1.0 — explicit dependency entry or named config file
      0.7 — file pattern with possible ambiguity
      0.5 — heuristic only; flag in ``note``
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import yaml

from pipeline.audit.kg import load_tool_index
from pipeline.audit.schemas import DetectedAgent, DetectedTool

# tomllib is stdlib >=3.11; fall back to tomli if needed.
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(repo_root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(repo_root))
    except ValueError:
        return str(p)


def _safe_read_text(path: Path, max_bytes: int = 512_000) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _exists(repo_root: Path, *parts: str) -> Path | None:
    p = repo_root.joinpath(*parts)
    return p if p.exists() else None


def _glob(repo_root: Path, pattern: str) -> list[Path]:
    """Glob within the repo root, ignoring vendored / virtualenv directories."""
    out: list[Path] = []
    for p in repo_root.glob(pattern):
        s = str(p)
        if any(seg in s for seg in (
            "/.git/", "/node_modules/", "/.venv/", "/venv/",
            "/__pycache__/", "/dist/", "/build/", "/.tox/",
        )):
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Stack-level signals
# ---------------------------------------------------------------------------

LANGUAGE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python",     ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
                    "requirements.txt")),
    ("typescript", ("tsconfig.json",)),
    ("javascript", ("package.json",)),
    ("go",         ("go.mod",)),
    ("rust",       ("Cargo.toml",)),
    ("java",       ("pom.xml", "build.gradle", "build.gradle.kts")),
    ("ruby",       ("Gemfile",)),
    ("php",        ("composer.json",)),
    ("csharp",     ("*.csproj",)),
)


def detect_languages(repo_root: Path) -> list[str]:
    """Heuristic language detection from canonical manifest files."""
    langs: list[str] = []
    for lang, markers in LANGUAGE_MARKERS:
        for marker in markers:
            if "*" in marker:
                if list(repo_root.glob(marker)):
                    langs.append(lang)
                    break
            elif (repo_root / marker).exists():
                langs.append(lang)
                break
    # Add JS as an implicit language whenever TS is present (a TS project
    # always compiles to JS) — but don't double-add.
    if "typescript" in langs and "javascript" not in langs:
        langs.append("javascript")
    return langs


def detect_runtime_hints(repo_root: Path) -> list[str]:
    """Return the marker filenames we actually saw, in canonical order."""
    seen: list[str] = []
    candidates = [
        "pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "setup.cfg",
        "package.json", "tsconfig.json", "yarn.lock", "pnpm-lock.yaml",
        "package-lock.json",
        "go.mod", "go.sum", "Cargo.toml", "Cargo.lock",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "Makefile", ".python-version", ".nvmrc", ".tool-versions",
    ]
    for c in candidates:
        if (repo_root / c).exists():
            seen.append(c)
    return seen


def detect_ci_providers(repo_root: Path) -> list[str]:
    """Detect CI/CD providers from config files."""
    providers: list[str] = []
    if (repo_root / ".github" / "workflows").is_dir():
        providers.append("github_actions")
    if (repo_root / ".gitlab-ci.yml").exists():
        providers.append("gitlab_ci")
    if (repo_root / ".circleci" / "config.yml").exists():
        providers.append("circle_ci")
    if (repo_root / "azure-pipelines.yml").exists():
        providers.append("azure_pipelines")
    if (repo_root / ".travis.yml").exists():
        providers.append("travis")
    if (repo_root / "Jenkinsfile").exists():
        providers.append("jenkins")
    if (repo_root / "buildkite.yml").exists() or (repo_root / ".buildkite").is_dir():
        providers.append("buildkite")
    return providers


def detect_package_managers(repo_root: Path) -> list[str]:
    """Detect package managers from lockfiles / manifests."""
    pm: list[str] = []
    if (repo_root / "pyproject.toml").exists():
        # Could be poetry, pdm, hatch, uv — all share the file. Keep generic.
        pm.append("pip")
        if (repo_root / "poetry.lock").exists():
            pm.append("poetry")
        if (repo_root / "uv.lock").exists():
            pm.append("uv")
        if (repo_root / "pdm.lock").exists():
            pm.append("pdm")
    elif any((repo_root / f).exists() for f in ("requirements.txt", "setup.py", "Pipfile")):
        pm.append("pip")
        if (repo_root / "Pipfile").exists():
            pm.append("pipenv")
    if (repo_root / "package.json").exists():
        if (repo_root / "pnpm-lock.yaml").exists():
            pm.append("pnpm")
        elif (repo_root / "yarn.lock").exists():
            pm.append("yarn")
        else:
            pm.append("npm")
    if (repo_root / "go.mod").exists():
        pm.append("go_modules")
    if (repo_root / "Cargo.toml").exists():
        pm.append("cargo")
    return pm


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

# (kg_id, name, [(path_or_glob, confidence)]).  First match wins per agent.
_AGENT_RULES: tuple[tuple[str, str, tuple[tuple[str, float], ...]], ...] = (
    ("claude-code", "Claude Code", (
        (".claude/", 1.0),
        ("CLAUDE.md", 1.0),
        (".claude.json", 1.0),
    )),
    ("cursor", "Cursor", (
        (".cursor/", 1.0),
        (".cursorrules", 1.0),
        (".cursorignore", 0.7),
    )),
    ("windsurf", "Windsurf", (
        (".windsurfrules", 1.0),
        (".codeium/", 0.7),
    )),
    ("zed-agent", "Zed Agent", (
        (".zed/settings.json", 0.7),
    )),
    ("aider", "Aider", (
        (".aider.conf.yml", 1.0),
        (".aider.chat.history.md", 0.7),
        (".aider.input.history", 0.5),
    )),
    ("github-copilot", "GitHub Copilot", (
        (".github/copilot/", 1.0),
        (".github/copilot-instructions.md", 1.0),
    )),
    ("continue-dev", "Continue", (
        (".continue/", 1.0),
        (".continuerc.json", 1.0),
    )),
    ("sourcegraph-cody", "Sourcegraph Cody", (
        (".sourcegraph/", 0.7),
        (".cody/", 0.7),
    )),
)


def detect_agents(repo_root: Path) -> list[DetectedAgent]:
    """Detect coding agents from config-file markers."""
    found: list[DetectedAgent] = []
    for agent_id, name, rules in _AGENT_RULES:
        paths: list[str] = []
        confidence = 0.0
        for marker, conf in rules:
            target = repo_root / marker.rstrip("/")
            if marker.endswith("/"):
                if target.is_dir():
                    paths.append(_rel(repo_root, target) + "/")
                    confidence = max(confidence, conf)
            elif "*" in marker:
                for p in repo_root.glob(marker):
                    paths.append(_rel(repo_root, p))
                    confidence = max(confidence, conf)
            elif target.exists():
                paths.append(_rel(repo_root, target))
                confidence = max(confidence, conf)
        if paths:
            found.append(DetectedAgent(
                id=agent_id,
                name=name,
                detection_paths=paths,
                confidence=confidence,
            ))
    return found


# ---------------------------------------------------------------------------
# Supervision tools — the big one
# ---------------------------------------------------------------------------

# (kg_id, name, github-actions "uses" prefix patterns).
_CI_ACTION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("semgrep", "Semgrep", (
        "semgrep/semgrep-action",
        "returntocorp/semgrep-action",
        "returntocorp/semgrep",
    )),
    ("snyk", "Snyk", (
        "snyk/actions",
    )),
    ("socket", "Socket", (
        "socketdev/",
        "socket-dev/",
    )),
    ("pr-agent", "Qodo Merge / PR-Agent", (
        "qodo-ai/pr-agent",
        "codium-ai/pr-agent",
        "Codium-ai/pr-agent",
    )),
)

# Python distribution-name → KG tool id.
# Keys are normalized to lower-case dashed form (PEP 503).
_PY_PKG_TO_TOOL: dict[str, tuple[str, str]] = {
    "guardrails-ai":   ("guardrails-ai",   "Guardrails AI"),
    "llm-guard":       ("llm-guard",       "LLM Guard"),
    "nemoguardrails":  ("nemo-guardrails", "NeMo Guardrails"),
    "instructor":      ("instructor",      "Instructor"),
    "pydantic-ai":     ("pydantic-ai",     "Pydantic AI"),
    "langgraph":       ("langgraph",       "LangGraph"),
    "langfuse":        ("langfuse",        "Langfuse"),
    "langsmith":       ("langsmith",       "LangSmith"),
    "crewai":          ("crewai",          "CrewAI"),
    "autogen-agentchat": ("autogen",       "AutoGen"),
    "pyautogen":       ("autogen",         "AutoGen"),
    "deepeval":        ("deepeval",        "DeepEval"),
    "ragas":           ("ragas",           "Ragas"),
    "garak":           ("garak",           "garak"),
    "pyrit":           ("pyrit",           "PyRIT"),
    "promptfoo":       ("promptfoo",       "promptfoo"),
    "litellm":         ("litellm",         "LiteLLM"),
    "helicone":        ("helicone",        "Helicone"),
}

# JS package-name → KG tool id.
_JS_PKG_TO_TOOL: dict[str, tuple[str, str]] = {
    "langfuse":               ("langfuse",  "Langfuse"),
    "langsmith":              ("langsmith", "LangSmith"),
    "helicone":               ("helicone",  "Helicone"),
    "litellm":                ("litellm",   "LiteLLM"),
    "@instructor-ai/instructor": ("instructor", "Instructor"),
    "promptfoo":              ("promptfoo", "promptfoo"),
}

# Eval / config files → KG tool id.
_EVAL_CONFIG_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("promptfoo", "promptfoo", (
        "promptfooconfig.yaml",
        "promptfooconfig.yml",
        "promptfooconfig.json",
    )),
    ("judgeval", "judgeval", (
        "judgeval/",
        "judgeval.yaml",
        "judgeval.yml",
    )),
    ("deepeval", "DeepEval", (
        ".deepeval/",
        "deepeval.yaml",
        "deepeval.yml",
    )),
    ("lm-evaluation-harness", "lm-evaluation-harness", (
        "lm-eval-config.yaml",
    )),
)


def _normalize_pep503(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of [-_.] → single '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement_line(line: str) -> str | None:
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    # Strip extras and version specifiers.
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return m.group(1) if m else None


def _python_packages_from_files(repo_root: Path) -> dict[str, list[str]]:
    """Return ``{normalized_pkg_name: [paths]}`` aggregated across Python manifests."""
    packages: dict[str, list[str]] = {}

    def add(pkg: str, src: Path) -> None:
        norm = _normalize_pep503(pkg)
        packages.setdefault(norm, []).append(_rel(repo_root, src))

    # pyproject.toml — handle both [project.dependencies] (PEP 621) and Poetry.
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            doc = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            doc = {}
        # PEP 621
        proj = doc.get("project") or {}
        for dep in (proj.get("dependencies") or []):
            name = _parse_requirement_line(str(dep))
            if name:
                add(name, pyproject)
        opt = proj.get("optional-dependencies") or {}
        if isinstance(opt, dict):
            for group in opt.values():
                for dep in group or []:
                    name = _parse_requirement_line(str(dep))
                    if name:
                        add(name, pyproject)
        # Poetry
        poetry = ((doc.get("tool") or {}).get("poetry") or {})
        for section in ("dependencies", "dev-dependencies"):
            sect = poetry.get(section) or {}
            if isinstance(sect, dict):
                for k in sect.keys():
                    if str(k).lower() == "python":
                        continue
                    add(str(k), pyproject)
        groups = (poetry.get("group") or {}) if isinstance(poetry.get("group"), dict) else {}
        for grp in groups.values():
            deps = (grp or {}).get("dependencies") or {}
            if isinstance(deps, dict):
                for k in deps.keys():
                    if str(k).lower() == "python":
                        continue
                    add(str(k), pyproject)
        # PDM / hatch dev groups live under [tool.pdm.dev-dependencies] or [tool.hatch...].
        pdm_dev = ((doc.get("tool") or {}).get("pdm") or {}).get("dev-dependencies") or {}
        if isinstance(pdm_dev, dict):
            for grp in pdm_dev.values():
                for dep in grp or []:
                    name = _parse_requirement_line(str(dep))
                    if name:
                        add(name, pyproject)

    # requirements*.txt
    for req in repo_root.glob("requirements*.txt"):
        for raw in _safe_read_text(req).splitlines():
            name = _parse_requirement_line(raw)
            if name:
                add(name, req)

    # Pipfile — naive parse: any [packages] / [dev-packages] line "key =".
    pipfile = repo_root / "Pipfile"
    if pipfile.exists():
        section = None
        for raw in _safe_read_text(pipfile).splitlines():
            s = raw.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1].strip().lower()
                continue
            if section in ("packages", "dev-packages"):
                m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=", s)
                if m:
                    add(m.group(1), pipfile)

    # setup.py — best-effort regex scan of install_requires=[...].
    setup_py = repo_root / "setup.py"
    if setup_py.exists():
        text = _safe_read_text(setup_py)
        m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if m:
            for raw in re.split(r"[,\n]", m.group(1)):
                raw = raw.strip().strip("'\"")
                name = _parse_requirement_line(raw)
                if name:
                    add(name, setup_py)

    return packages


def _js_packages_from_package_json(repo_root: Path) -> dict[str, list[str]]:
    pkg_path = repo_root / "package.json"
    if not pkg_path.exists():
        return {}
    try:
        doc = json.loads(_safe_read_text(pkg_path))
    except (json.JSONDecodeError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        deps = doc.get(section) or {}
        if isinstance(deps, dict):
            for name in deps.keys():
                out.setdefault(str(name).lower(), []).append(_rel(repo_root, pkg_path))
    return out


def _ci_action_uses(repo_root: Path) -> list[tuple[str, str]]:
    """Return list of ``(uses_value, source_path)`` from GH Actions workflow files."""
    out: list[tuple[str, str]] = []
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return out
    for wf in list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml")):
        text = _safe_read_text(wf)
        # Cheap line-based scan first (faster + tolerant of malformed YAML).
        for line in text.splitlines():
            m = re.search(r"uses:\s*['\"]?([^\s'\"]+)['\"]?", line)
            if m:
                out.append((m.group(1), _rel(repo_root, wf)))
    return out


def detect_supervision_tools(repo_root: Path) -> list[DetectedTool]:
    """Detect supervision tools across all signal sources.

    Returns one :class:`DetectedTool` per (kg_id, source) pair so the same
    tool found in multiple places (e.g. Python dep + CI workflow) shows up
    with both rationales rather than getting merged.  Coverage logic later
    deduplicates by id.
    """
    kg = load_tool_index()
    out: list[DetectedTool] = []
    seen_keys: set[tuple[str, str]] = set()

    def emit(kg_id: str, name: str, source: str, paths: list[str],
             confidence: float, note: str | None = None) -> None:
        in_kg = kg_id in kg
        key = (kg_id, source)
        if key in seen_keys:
            return
        seen_keys.add(key)
        out.append(DetectedTool(
            id=kg_id if in_kg else "",
            name=kg.get(kg_id, {}).get("name", name) if in_kg else name,
            in_kg=in_kg,
            detection_source=source,  # type: ignore[arg-type]
            detection_paths=sorted(set(paths)),
            confidence=confidence,
            note=note,
        ))

    # --- CI workflow `uses:` lines ----------------------------------------
    uses_pairs = _ci_action_uses(repo_root)
    for kg_id, name, prefixes in _CI_ACTION_RULES:
        matched_paths: list[str] = []
        for uses, src in uses_pairs:
            uses_lower = uses.lower()
            if any(uses_lower.startswith(p.lower()) for p in prefixes):
                matched_paths.append(src)
        if matched_paths:
            emit(kg_id, name, "ci_workflow", matched_paths, 1.0)

    # --- Dependabot config -------------------------------------------------
    if (p := _exists(repo_root, ".github", "dependabot.yml")) or \
       (p := _exists(repo_root, ".github", "dependabot.yaml")):
        emit("dependabot", "Dependabot", "dependabot",
             [_rel(repo_root, p)], 1.0)

    # --- Renovate config ---------------------------------------------------
    renovate_paths: list[str] = []
    for cand in ("renovate.json", ".github/renovate.json", ".renovaterc",
                 ".renovaterc.json", ".renovaterc.json5", "renovate.json5"):
        if (p := _exists(repo_root, *cand.split("/"))):
            renovate_paths.append(_rel(repo_root, p))
    if renovate_paths:
        emit("renovate", "Renovate", "renovate", renovate_paths, 1.0)

    # --- pre-commit framework itself --------------------------------------
    if (p := _exists(repo_root, ".pre-commit-config.yaml")) or \
       (p := _exists(repo_root, ".pre-commit-config.yml")):
        # The framework itself is `pre-commit`. We ALSO scan for tools
        # referenced inside the config (semgrep, etc.) below.
        emit("pre-commit", "pre-commit", "pre_commit",
             [_rel(repo_root, p)], 1.0,
             note="Detected the pre-commit framework; underlying hooks also scanned.")
        # Look for semgrep among hooks → high-confidence semgrep detection.
        text = _safe_read_text(p)
        if re.search(r"semgrep", text, re.IGNORECASE):
            emit("semgrep", "Semgrep", "pre_commit",
                 [_rel(repo_root, p)], 1.0)

    # --- Python deps -------------------------------------------------------
    py_pkgs = _python_packages_from_files(repo_root)
    for pkg_name, paths in py_pkgs.items():
        if pkg_name in _PY_PKG_TO_TOOL:
            kg_id, display = _PY_PKG_TO_TOOL[pkg_name]
            emit(kg_id, display, "dep_file", paths, 1.0)

    # --- JS deps -----------------------------------------------------------
    js_pkgs = _js_packages_from_package_json(repo_root)
    for pkg_name, paths in js_pkgs.items():
        key = pkg_name.lower()
        if key in _JS_PKG_TO_TOOL:
            kg_id, display = _JS_PKG_TO_TOOL[key]
            emit(kg_id, display, "dep_file", paths, 1.0)

    # --- Eval configs ------------------------------------------------------
    for kg_id, name, candidates in _EVAL_CONFIG_RULES:
        matched: list[str] = []
        for cand in candidates:
            target = repo_root / cand.rstrip("/")
            if cand.endswith("/"):
                if target.is_dir():
                    matched.append(_rel(repo_root, target) + "/")
            elif target.exists():
                matched.append(_rel(repo_root, target))
        if matched:
            emit(kg_id, name, "eval_config", matched, 1.0)

    return out


__all__ = [
    "detect_agents",
    "detect_ci_providers",
    "detect_languages",
    "detect_package_managers",
    "detect_runtime_hints",
    "detect_supervision_tools",
]
