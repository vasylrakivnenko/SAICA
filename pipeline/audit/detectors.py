"""Detection rules for the audit analyzer.

Each function takes the root of a checked-out (or fetched) repository and
returns one slice of the detected stack. Detection is **conservative**: it
is better to miss a tool than to tell a user they have one installed when
they do not.

What the audit can see, and nothing else:

* files in the repository root and a few fixed sub-folders
  (``.github/workflows``, ``.circleci``, ``.zed``); a manifest in a
  sub-package (``python/pyproject.toml``) is not seen;
* four mechanisms: ``uses:`` steps (and job container images) of GitHub
  Actions workflows, dependency names in Python and JavaScript manifests, ``[tool.<name>]``
  tables in ``pyproject.toml``, and a short list of named config files
  (pre-commit hooks, Dependabot, Renovate, eval configs).

Every path the detectors look at is declared in the tables of this
module. :func:`fetch_plan` derives from the same tables which files a
remote fetch must download and which only need to exist, so a remote
audit and a local one read the same inputs.

Conventions:
  * A ``DetectedTool`` whose rule points at an id that is in the KG has
    ``in_kg=True``. A rule that points at an id the KG does not hold (the
    catalog dropped it, or never had it) yields ``in_kg=False`` with an
    empty id; the report lists those separately and they add no coverage.
  * Each detection records the file paths (relative to the repo root)
    that triggered it.
  * ``confidence``: 1.0 for a dependency entry, a workflow step or a
    named config file; 0.9 for a ``[tool.<name>]`` table.
  * A commented-out line is not a detection. Workflows and pre-commit
    configs are parsed as YAML; a file that does not parse falls back to a
    line scan that skips comment lines (workflows) or yields nothing
    (pre-commit hooks).
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

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

# No detector reads more of a file than this.
MAX_READ_BYTES = 512_000


def _rel(repo_root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(repo_root))
    except ValueError:
        return str(p)


def _safe_read_text(path: Path, max_bytes: int = MAX_READ_BYTES) -> str:
    """File content as text; undecodable bytes are replaced, never raised."""
    try:
        with path.open("rb") as fh:
            data = fh.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _exists(repo_root: Path, *parts: str) -> Path | None:
    p = repo_root.joinpath(*parts)
    return p if p.exists() else None


def _as_dict(value: Any) -> dict:
    """``value`` if it is a mapping, else an empty one."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _load_toml(path: Path) -> dict:
    """Parse a TOML file; ``{}`` when it is missing, undecodable or invalid."""
    if not path.is_file():
        return {}
    try:
        return _as_dict(tomllib.loads(_safe_read_text(path)))
    except (tomllib.TOMLDecodeError, ValueError, RecursionError):
        return {}


def _load_json_object(path: Path) -> dict:
    """Parse a JSON file; ``{}`` unless its top level is an object."""
    if not path.is_file():
        return {}
    try:
        return _as_dict(json.loads(_safe_read_text(path)))
    except (ValueError, RecursionError):
        return {}


def _load_yaml(path: Path) -> Any:
    """Parse a YAML file; ``None`` when it is missing or does not parse."""
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(_safe_read_text(path))
    except (yaml.YAMLError, ValueError, RecursionError):
        return None


# ---------------------------------------------------------------------------
# Stack-level signals
# ---------------------------------------------------------------------------

LANGUAGE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "python",
        ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt"),
    ),
    ("typescript", ("tsconfig.json",)),
    ("javascript", ("package.json",)),
    ("go", ("go.mod",)),
    ("rust", ("Cargo.toml",)),
    ("java", ("pom.xml", "build.gradle", "build.gradle.kts")),
    ("ruby", ("Gemfile",)),
    ("php", ("composer.json",)),
    ("csharp", ("*.csproj",)),
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


# Marker files reported as "runtime hints", in display order.
RUNTIME_HINT_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "package.json",
    "tsconfig.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    ".python-version",
    ".nvmrc",
    ".tool-versions",
)

# (provider, markers). A marker ending in "/" is a folder.
CI_PROVIDER_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("github_actions", (".github/workflows/",)),
    ("gitlab_ci", (".gitlab-ci.yml",)),
    ("circle_ci", (".circleci/config.yml",)),
    ("azure_pipelines", ("azure-pipelines.yml",)),
    ("travis", (".travis.yml",)),
    ("jenkins", ("Jenkinsfile",)),
    ("buildkite", ("buildkite.yml", ".buildkite/")),
)

# Lock files that name a package manager.
PACKAGE_MANAGER_LOCKS: tuple[str, ...] = (
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
    "pnpm-lock.yaml",
    "yarn.lock",
)


def _marker_present(repo_root: Path, marker: str) -> bool:
    target = repo_root / marker.rstrip("/")
    return target.is_dir() if marker.endswith("/") else target.exists()


def detect_runtime_hints(repo_root: Path) -> list[str]:
    """Return the marker filenames we actually saw, in canonical order."""
    return [c for c in RUNTIME_HINT_FILES if (repo_root / c).exists()]


def detect_ci_providers(repo_root: Path) -> list[str]:
    """Detect CI/CD providers from config files."""
    return [
        provider
        for provider, markers in CI_PROVIDER_MARKERS
        if any(_marker_present(repo_root, m) for m in markers)
    ]


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
    elif any(
        (repo_root / f).exists() for f in ("requirements.txt", "setup.py", "Pipfile")
    ):
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
    (
        "claude-code",
        "Claude Code",
        (
            (".claude/", 1.0),
            ("CLAUDE.md", 1.0),
            (".claude.json", 1.0),
        ),
    ),
    (
        "cursor",
        "Cursor",
        (
            (".cursor/", 1.0),
            (".cursorrules", 1.0),
            (".cursorignore", 0.7),
        ),
    ),
    (
        "windsurf",
        "Windsurf",
        (
            (".windsurfrules", 1.0),
            (".codeium/", 0.7),
        ),
    ),
    ("zed-agent", "Zed Agent", ((".zed/settings.json", 0.7),)),
    (
        "aider",
        "Aider",
        (
            (".aider.conf.yml", 1.0),
            (".aider.chat.history.md", 0.7),
            (".aider.input.history", 0.5),
        ),
    ),
    (
        "github-copilot",
        "GitHub Copilot",
        (
            (".github/copilot/", 1.0),
            (".github/copilot-instructions.md", 1.0),
        ),
    ),
    (
        "continue-dev",
        "Continue",
        (
            (".continue/", 1.0),
            (".continuerc.json", 1.0),
        ),
    ),
    (
        "sourcegraph-cody",
        "Sourcegraph Cody",
        (
            (".sourcegraph/", 0.7),
            (".cody/", 0.7),
        ),
    ),
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
            found.append(
                DetectedAgent(
                    id=agent_id,
                    name=name,
                    detection_paths=paths,
                    confidence=confidence,
                )
            )
    return found


# ---------------------------------------------------------------------------
# Supervision tools — the big one
# ---------------------------------------------------------------------------

# (kg_id, name, github-actions "uses" prefix patterns).
_CI_ACTION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "semgrep",
        "Semgrep",
        (
            "semgrep/semgrep-action",
            "returntocorp/semgrep-action",
            "returntocorp/semgrep",
        ),
    ),
    ("snyk", "Snyk", ("snyk/actions",)),
    (
        "socket",
        "Socket",
        (
            "socketdev/",
            "socket-dev/",
        ),
    ),
    (
        "pr-agent",
        "Qodo Merge / PR-Agent",
        (
            "qodo-ai/pr-agent",
            "codium-ai/pr-agent",
            "Codium-ai/pr-agent",
        ),
    ),
)

# (kg_id, name, container-image prefixes). A job that runs in the tool's
# own image (``container: {image: semgrep/semgrep}``, the form Semgrep
# documents today) uses the tool even without a ``uses:`` step.
_CI_CONTAINER_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("semgrep", "Semgrep", ("semgrep/semgrep", "returntocorp/semgrep")),
)

# Python distribution-name → KG tool id.
# Keys are normalized to lower-case dashed form (PEP 503).
_PY_PKG_TO_TOOL: dict[str, tuple[str, str]] = {
    "guardrails-ai": ("guardrails-ai", "Guardrails AI"),
    "llm-guard": ("llm-guard", "LLM Guard"),
    "nemoguardrails": ("nemo-guardrails", "NeMo Guardrails"),
    "instructor": ("instructor", "Instructor"),
    "pydantic-ai": ("pydantic-ai", "Pydantic AI"),
    "langgraph": ("langgraph", "LangGraph"),
    "langfuse": ("langfuse", "Langfuse"),
    "langsmith": ("langsmith", "LangSmith"),
    "crewai": ("crewai", "CrewAI"),
    "autogen-agentchat": ("autogen", "AutoGen"),
    "pyautogen": ("autogen", "AutoGen"),
    "deepeval": ("deepeval", "DeepEval"),
    "ragas": ("ragas", "Ragas"),
    "garak": ("garak", "garak"),
    "pyrit": ("pyrit", "PyRIT"),
    "promptfoo": ("promptfoo", "promptfoo"),
    "litellm": ("litellm", "LiteLLM"),
    "helicone": ("helicone", "Helicone"),
}

# JS package-name → KG tool id.
_JS_PKG_TO_TOOL: dict[str, tuple[str, str]] = {
    "langfuse": ("langfuse", "Langfuse"),
    "langsmith": ("langsmith", "LangSmith"),
    "helicone": ("helicone", "Helicone"),
    "litellm": ("litellm", "LiteLLM"),
    "@instructor-ai/instructor": ("instructor", "Instructor"),
    "promptfoo": ("promptfoo", "promptfoo"),
    # Plain dev-tool deps (added in v0.4.2 to lift detection floor on
    # well-maintained JS/TS projects whose pyproject analogue is
    # package.json `devDependencies`).
    "eslint": ("eslint", "ESLint"),
    "prettier": ("prettier", "Prettier"),
}

# pyproject.toml `[tool.<name>]` second-component → KG tool id.
#
# Added in v0.4.2 after surveying openai-python, anthropic-sdk-python,
# fastapi, pydantic, httpx, ruff: every well-maintained Python repo in
# 2026 declares its dev-tooling here rather than via .pre-commit-config
# or a custom CI step. Scanning only `.pre-commit-config.yaml` /
# action `uses:` refs missed all of them — this rule closes that gap.
#
# Match is on the SECOND path component (`tool.<X>` or `tool.<X>.<...>`),
# so `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.pytest.ini_options]`,
# `[tool.coverage.run]` all hit the same KG id once. Build/packaging
# sections (poetry, hatch, uv, pdm, rye, maturin) are deliberately
# omitted — they're not supervisors.
_PYPROJECT_TOOL_TO_KG: dict[str, tuple[str, str]] = {
    "ruff": ("ruff", "Ruff"),
    "mypy": ("mypy", "mypy"),
    "pyright": ("pyright", "Pyright"),
    "pytest": ("pytest", "pytest"),
    "black": ("black", "Black"),
    "isort": ("isort", "isort"),
    "coverage": ("coverage-py", "Coverage.py"),
    "bandit": ("bandit", "Bandit"),
}

# Eval / config files → KG tool id.
_EVAL_CONFIG_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "promptfoo",
        "promptfoo",
        (
            "promptfooconfig.yaml",
            "promptfooconfig.yml",
            "promptfooconfig.json",
        ),
    ),
    (
        "judgeval",
        "judgeval",
        (
            "judgeval/",
            "judgeval.yaml",
            "judgeval.yml",
        ),
    ),
    (
        "deepeval",
        "DeepEval",
        (
            ".deepeval/",
            "deepeval.yaml",
            "deepeval.yml",
        ),
    ),
    ("lm-evaluation-harness", "lm-evaluation-harness", ("lm-eval-config.yaml",)),
)


# Config files that are themselves the detection (presence is enough).
DEPENDABOT_FILES: tuple[str, ...] = (
    ".github/dependabot.yml",
    ".github/dependabot.yaml",
)
RENOVATE_FILES: tuple[str, ...] = (
    "renovate.json",
    ".github/renovate.json",
    ".renovaterc",
    ".renovaterc.json",
    ".renovaterc.json5",
    "renovate.json5",
)
PRE_COMMIT_FILES: tuple[str, ...] = (
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
)

# pre-commit ``repos[].repo`` (GitHub "owner/name", lower-case) → KG tool id.
_PRE_COMMIT_REPO_TO_TOOL: dict[str, tuple[str, str]] = {
    "semgrep/semgrep": ("semgrep", "Semgrep"),
    "semgrep/pre-commit": ("semgrep", "Semgrep"),
    "returntocorp/semgrep": ("semgrep", "Semgrep"),
    "astral-sh/ruff-pre-commit": ("ruff", "Ruff"),
    "charliermarsh/ruff-pre-commit": ("ruff", "Ruff"),
    "pre-commit/mirrors-mypy": ("mypy", "mypy"),
    "pycqa/bandit": ("bandit", "Bandit"),
    "robertcraigie/pyright-python": ("pyright", "Pyright"),
    "pre-commit/mirrors-eslint": ("eslint", "ESLint"),
}

# pre-commit ``hooks[].id`` → KG tool id, for hooks under ``repo: local``.
_PRE_COMMIT_HOOK_TO_TOOL: dict[str, tuple[str, str]] = {
    "semgrep": ("semgrep", "Semgrep"),
    "ruff": ("ruff", "Ruff"),
    "mypy": ("mypy", "mypy"),
    "bandit": ("bandit", "Bandit"),
    "pyright": ("pyright", "Pyright"),
    "eslint": ("eslint", "ESLint"),
}

# Files whose *content* the detectors read. Everything else in the tables
# above is a presence check. A pattern matches paths of the same depth
# only ("requirements*.txt" does not match "requirements/dev.txt").
CONTENT_PATTERNS: tuple[str, ...] = (
    "pyproject.toml",
    "requirements*.txt",
    "Pipfile",
    "setup.py",
    "package.json",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
) + PRE_COMMIT_FILES


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
    """Return ``{normalized_pkg_name: [paths]}`` aggregated across Python manifests.

    Never raises on an odd manifest: a section of the wrong type is skipped.
    """
    packages: dict[str, list[str]] = {}

    def add(pkg: str, src: Path) -> None:
        norm = _normalize_pep503(pkg)
        packages.setdefault(norm, []).append(_rel(repo_root, src))

    def add_requirements(deps: Any, src: Path) -> None:
        for dep in _as_list(deps):
            name = _parse_requirement_line(str(dep))
            if name:
                add(name, src)

    def add_keys(table: Any, src: Path) -> None:
        for key in _as_dict(table):
            if str(key).lower() != "python":
                add(str(key), src)

    # pyproject.toml — [project] (PEP 621), Poetry, PDM.
    pyproject = repo_root / "pyproject.toml"
    doc = _load_toml(pyproject)
    proj = _as_dict(doc.get("project"))
    add_requirements(proj.get("dependencies"), pyproject)
    for group in _as_dict(proj.get("optional-dependencies")).values():
        add_requirements(group, pyproject)
    tool_table = _as_dict(doc.get("tool"))
    poetry = _as_dict(tool_table.get("poetry"))
    for section in ("dependencies", "dev-dependencies"):
        add_keys(poetry.get(section), pyproject)
    for grp in _as_dict(poetry.get("group")).values():
        add_keys(_as_dict(grp).get("dependencies"), pyproject)
    pdm_dev = _as_dict(_as_dict(tool_table.get("pdm")).get("dev-dependencies"))
    for grp in pdm_dev.values():
        add_requirements(grp, pyproject)

    # requirements*.txt
    for req in sorted(repo_root.glob("requirements*.txt")):
        for raw in _safe_read_text(req).splitlines():
            name = _parse_requirement_line(raw)
            if name:
                add(name, req)

    # Pipfile — naive parse: any [packages] / [dev-packages] line "key =".
    pipfile = repo_root / "Pipfile"
    if pipfile.is_file():
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

    # setup.py — best-effort scan of install_requires=[...]; comment lines
    # inside the list are dropped by _parse_requirement_line.
    setup_py = repo_root / "setup.py"
    if setup_py.is_file():
        text = _safe_read_text(setup_py)
        m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if line.strip().startswith("#"):
                    continue
                for raw in line.split(","):
                    name = _parse_requirement_line(raw.strip().strip("'\""))
                    if name:
                        add(name, setup_py)

    return packages


def _pyproject_tool_sections(repo_root: Path) -> dict[str, str]:
    """Return ``{tool_name: pyproject_path}`` for every ``[tool.<name>]``
    table in the repo's ``pyproject.toml``.

    Match is on the SECOND path component, so ``[tool.ruff]``,
    ``[tool.ruff.lint]``, ``[tool.pytest.ini_options]`` all collapse to
    ``ruff`` / ``pytest``. Empty when there is no readable ``[tool]`` table.
    """
    pyproject = repo_root / "pyproject.toml"
    tool_table = _as_dict(_load_toml(pyproject).get("tool"))
    rel_path = _rel(repo_root, pyproject)
    return {str(name): rel_path for name in tool_table}


def _js_packages_from_package_json(repo_root: Path) -> dict[str, list[str]]:
    pkg_path = repo_root / "package.json"
    doc = _load_json_object(pkg_path)
    out: dict[str, list[str]] = {}
    for section in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        for name in _as_dict(doc.get(section)):
            out.setdefault(str(name).lower(), []).append(_rel(repo_root, pkg_path))
    return out


_USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^\s'\"#]+)")


def _uses_from_workflow(doc: Any) -> list[str]:
    """``uses:`` values of a parsed workflow: job steps and reusable jobs."""
    out: list[str] = []
    for job in _as_dict(_as_dict(doc).get("jobs")).values():
        job = _as_dict(job)
        if isinstance(job.get("uses"), str):
            out.append(job["uses"])
        for step in _as_list(job.get("steps")):
            uses = _as_dict(step).get("uses")
            if isinstance(uses, str):
                out.append(uses)
    return out


def _container_images(repo_root: Path) -> list[tuple[str, str]]:
    """``(image, source_path)`` for every job container of parsed workflows."""
    out: list[tuple[str, str]] = []
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return out
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    for wf in files:
        for job in _as_dict(_as_dict(_load_yaml(wf)).get("jobs")).values():
            container = _as_dict(job).get("container")
            image = (
                container
                if isinstance(container, str)
                else _as_dict(container).get("image")
            )
            if isinstance(image, str):
                out.append((image.strip(), _rel(repo_root, wf)))
    return out


def _ci_action_uses(repo_root: Path) -> list[tuple[str, str]]:
    """Return ``(uses_value, source_path)`` pairs from GitHub Actions workflows.

    A workflow is parsed as YAML, so a commented-out step or a ``uses:``
    inside a shell script is not counted. A file that does not parse is
    scanned line by line, skipping comment lines.
    """
    out: list[tuple[str, str]] = []
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return out
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    for wf in files:
        src = _rel(repo_root, wf)
        doc = _load_yaml(wf)
        if isinstance(doc, dict):
            out.extend((uses.strip(), src) for uses in _uses_from_workflow(doc))
            continue
        for line in _safe_read_text(wf).splitlines():
            if line.lstrip().startswith("#"):
                continue
            m = _USES_LINE_RE.match(line)
            if m:
                out.append((m.group(1), src))
    return out


_GITHUB_REPO_RE = re.compile(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def _pre_commit_tools(path: Path) -> list[tuple[str, str]]:
    """``(kg_id, display name)`` for the hooks a pre-commit config declares.

    Reads ``repos[].repo`` and ``repos[].hooks[].id`` of the parsed YAML. A
    word in a comment, or a file that does not parse, yields nothing.
    """
    found: dict[str, str] = {}
    for repo in _as_list(_as_dict(_load_yaml(path)).get("repos")):
        repo = _as_dict(repo)
        url = repo.get("repo")
        hooks = [_as_dict(h) for h in _as_list(repo.get("hooks"))]
        if not hooks:
            continue  # a repo entry without hooks runs nothing
        m = _GITHUB_REPO_RE.search(url.strip()) if isinstance(url, str) else None
        if m:
            target = _PRE_COMMIT_REPO_TO_TOOL.get(f"{m.group(1)}/{m.group(2)}".lower())
            if target:
                found.setdefault(*target)
        elif url == "local":
            for hook in hooks:
                target = _PRE_COMMIT_HOOK_TO_TOOL.get(str(hook.get("id") or "").lower())
                if target:
                    found.setdefault(*target)
    return list(found.items())


def detect_supervision_tools(repo_root: Path) -> list[DetectedTool]:
    """Detect supervision tools across all signal sources.

    Returns one :class:`DetectedTool` per (kg_id, source) pair, so a tool
    found in two places shows both reasons. Count tools by distinct id.
    """
    kg = load_tool_index()
    out: list[DetectedTool] = []
    seen_keys: set[tuple[str, str]] = set()

    def emit(
        kg_id: str,
        name: str,
        source: str,
        paths: list[str],
        confidence: float,
        note: str | None = None,
    ) -> None:
        in_kg = kg_id in kg
        key = (kg_id, source)
        if key in seen_keys:
            return
        seen_keys.add(key)
        out.append(
            DetectedTool(
                id=kg_id if in_kg else "",
                name=kg[kg_id].get("name", name) if in_kg else name,
                in_kg=in_kg,
                detection_source=source,  # type: ignore[arg-type]
                detection_paths=sorted(set(paths)),
                confidence=confidence,
                note=note,
            )
        )

    # --- CI workflow `uses:` steps ----------------------------------------
    uses_pairs = _ci_action_uses(repo_root)
    for kg_id, name, prefixes in _CI_ACTION_RULES:
        matched_paths: list[str] = []
        for uses, src in uses_pairs:
            uses_lower = uses.lower()
            if any(uses_lower.startswith(p.lower()) for p in prefixes):
                matched_paths.append(src)
        if matched_paths:
            emit(kg_id, name, "ci_workflow", matched_paths, 1.0)

    # --- CI jobs that run in the tool's own container image -----------------
    images = _container_images(repo_root)
    for kg_id, name, prefixes in _CI_CONTAINER_RULES:
        matched_paths = [
            src
            for image, src in images
            if any(
                image.lower().removeprefix("docker.io/").split(":")[0].split("@")[0]
                == p
                for p in prefixes
            )
        ]
        if matched_paths:
            emit(kg_id, name, "ci_workflow", matched_paths, 1.0)

    # --- Dependabot config -------------------------------------------------
    for cand in DEPENDABOT_FILES:
        if p := _exists(repo_root, *cand.split("/")):
            emit("dependabot", "Dependabot", "dependabot", [_rel(repo_root, p)], 1.0)
            break

    # --- Renovate config ---------------------------------------------------
    renovate_paths = [
        _rel(repo_root, p)
        for cand in RENOVATE_FILES
        if (p := _exists(repo_root, *cand.split("/")))
    ]
    if renovate_paths:
        emit("renovate", "Renovate", "renovate", renovate_paths, 1.0)

    # --- pre-commit: the framework, then the hooks it runs -----------------
    for cand in PRE_COMMIT_FILES:
        if p := _exists(repo_root, cand):
            emit("pre-commit", "pre-commit", "pre_commit", [_rel(repo_root, p)], 1.0)
            for kg_id, name in _pre_commit_tools(p):
                emit(kg_id, name, "pre_commit", [_rel(repo_root, p)], 1.0)
            break

    # --- Python deps -------------------------------------------------------
    py_pkgs = _python_packages_from_files(repo_root)
    for pkg_name, paths in py_pkgs.items():
        if pkg_name in _PY_PKG_TO_TOOL:
            kg_id, display = _PY_PKG_TO_TOOL[pkg_name]
            emit(kg_id, display, "dep_file", paths, 1.0)

    # --- JS deps -----------------------------------------------------------
    js_pkgs = _js_packages_from_package_json(repo_root)
    for pkg_name, paths in js_pkgs.items():
        if pkg_name in _JS_PKG_TO_TOOL:
            kg_id, display = _JS_PKG_TO_TOOL[pkg_name]
            emit(kg_id, display, "dep_file", paths, 1.0)

    # --- pyproject.toml `[tool.<name>]` tables -----------------------------
    for tool_name, src in _pyproject_tool_sections(repo_root).items():
        if tool_name in _PYPROJECT_TOOL_TO_KG:
            kg_id, display = _PYPROJECT_TOOL_TO_KG[tool_name]
            emit(
                kg_id,
                display,
                "dep_file",
                [src],
                0.9,
                note=f"Declared via [tool.{tool_name}] in pyproject.toml",
            )

    # --- Eval configs ------------------------------------------------------
    for kg_id, name, candidates in _EVAL_CONFIG_RULES:
        matched = [
            _rel(repo_root, repo_root / cand.rstrip("/"))
            + ("/" if cand.endswith("/") else "")
            for cand in candidates
            if _marker_present(repo_root, cand)
        ]
        if matched:
            emit(kg_id, name, "eval_config", matched, 1.0)

    return out


# ---------------------------------------------------------------------------
# What the rules can see (used for the report's limits and for remote fetch)
# ---------------------------------------------------------------------------


def rule_target_ids() -> frozenset[str]:
    """Every tool id some detection rule can emit, in the KG or not."""
    ids: set[str] = {"dependabot", "renovate", "pre-commit"}
    ids.update(kg_id for kg_id, _, _ in _CI_ACTION_RULES)
    ids.update(kg_id for kg_id, _, _ in _CI_CONTAINER_RULES)
    ids.update(kg_id for kg_id, _, _ in _EVAL_CONFIG_RULES)
    for table in (
        _PY_PKG_TO_TOOL,
        _JS_PKG_TO_TOOL,
        _PYPROJECT_TOOL_TO_KG,
        _PRE_COMMIT_REPO_TO_TOOL,
        _PRE_COMMIT_HOOK_TO_TOOL,
    ):
        ids.update(kg_id for kg_id, _ in table.values())
    return frozenset(ids)


def detectable_tool_ids(kg_index: dict[str, dict] | None = None) -> frozenset[str]:
    """KG tools the audit has at least one detection rule for."""
    kg = kg_index if kg_index is not None else load_tool_index()
    return frozenset(rule_target_ids() & set(kg))


def presence_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(files, folders)`` the detectors only test for existence.

    Derived from the rule tables, so the list cannot drift from the rules.
    File entries may be root-level patterns (``*.csproj``).
    """
    files: set[str] = set(RUNTIME_HINT_FILES) | set(PACKAGE_MANAGER_LOCKS)
    files.update(DEPENDABOT_FILES)
    files.update(RENOVATE_FILES)
    folders: set[str] = set()
    markers: list[str] = []
    markers.extend(m for _, group in LANGUAGE_MARKERS for m in group)
    markers.extend(m for _, group in CI_PROVIDER_MARKERS for m in group)
    markers.extend(m for _, _, rules in _AGENT_RULES for m, _ in rules)
    markers.extend(m for _, _, group in _EVAL_CONFIG_RULES for m in group)
    for marker in markers:
        (folders if marker.endswith("/") else files).add(marker.rstrip("/"))
    files -= {f for f in files if any(_matches(f, pat) for pat in CONTENT_PATTERNS)}
    return tuple(sorted(files)), tuple(sorted(folders))


def _matches(path: str, pattern: str) -> bool:
    """fnmatch that never lets ``*`` cross a ``/``."""
    return path.count("/") == pattern.count("/") and fnmatch.fnmatchcase(path, pattern)


def fetch_plan(
    blob_paths: list[str], tree_paths: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Split a repository listing into what a remote audit needs.

    ``blob_paths`` are the files and ``tree_paths`` the folders of the
    repository, relative to its root. Returns ``(content, files, folders)``:
    files to download, files that only have to exist (an empty placeholder
    is enough), and folders that only have to exist. Each list is sorted.
    """
    presence_files, presence_dirs = presence_markers()
    content = sorted(
        p for p in blob_paths if any(_matches(p, pat) for pat in CONTENT_PATTERNS)
    )
    files = sorted(
        p
        for p in blob_paths
        if p not in content and any(_matches(p, pat) for pat in presence_files)
    )
    wanted_dirs = set(presence_dirs)
    folders = sorted(
        d
        for d in wanted_dirs
        if d in tree_paths or any(p.startswith(d + "/") for p in blob_paths)
    )
    return content, files, folders


__all__ = [
    "CONTENT_PATTERNS",
    "MAX_READ_BYTES",
    "detect_agents",
    "detect_ci_providers",
    "detect_languages",
    "detect_package_managers",
    "detect_runtime_hints",
    "detect_supervision_tools",
    "detectable_tool_ids",
    "fetch_plan",
    "presence_markers",
    "rule_target_ids",
]
