"""Smoke tests for the SAICA-KG MCP server.

These exercise the *pure-function* layer (no MCP transport spin-up). The
server module is also imported to confirm it has no import-time errors.
"""
from __future__ import annotations

import pytest

from pipeline.mcp._schemas_compat import PreflightResult, ToolRecord
from pipeline.mcp.lookup import saica_lookup
from pipeline.mcp.preflight import (
    assess_severity,
    classify_action,
    saica_preflight,
)


# ---------------------------------------------------------------------------
# saica_lookup
# ---------------------------------------------------------------------------

def test_lookup_semgrep_returns_full_tool_record() -> None:
    rec = saica_lookup("semgrep")
    assert isinstance(rec, ToolRecord)
    assert rec.id == "semgrep"
    assert rec.name  # non-empty
    assert rec.description  # non-empty
    assert rec.control_paradigm == "detection"
    # Surfaces should include at least one pipeline-friendly entry.
    assert rec.integration_surfaces, "integration_surfaces must not be empty"
    assert "cli" in rec.integration_surfaces or "ci_app" in rec.integration_surfaces
    assert rec.url == "/tools/semgrep"
    # Should declare coverage for at least one failure mode.
    assert rec.addresses_failure_modes


def test_lookup_unknown_tool_raises_clear_error() -> None:
    with pytest.raises(ValueError) as ei:
        saica_lookup("nonexistent-tool-foo")
    msg = str(ei.value)
    assert "nonexistent-tool-foo" in msg
    # The hint pointing the agent to a follow-up call is the contract
    # promise the server module's docstring makes.
    assert "saica_search" in msg or "tool-coverage" in msg


# ---------------------------------------------------------------------------
# saica_preflight — destructive shell action
# ---------------------------------------------------------------------------

def test_preflight_rm_rf_is_high_risk_with_security_or_cascading() -> None:
    result = saica_preflight("rm -rf /", None, None)
    assert isinstance(result, PreflightResult)
    assert result.overall_risk == "high"
    # rm -rf must trip *at least* one of the two destructive-shell FMs.
    assert (
        "cascading_failure" in result.risk_failure_modes
        or "security_vulnerability" in result.risk_failure_modes
    )
    # Recommendations must be non-empty and well-formed.
    assert result.recommended_supervisors
    for rec in result.recommended_supervisors:
        assert rec.tool_id
        assert rec.tool_name
        assert rec.url.startswith("/tools/")


# ---------------------------------------------------------------------------
# saica_preflight — supply-chain action
# ---------------------------------------------------------------------------

def test_preflight_install_left_pad_recommends_supply_chain_tool() -> None:
    result = saica_preflight("install left-pad", None, None)
    assert isinstance(result, PreflightResult)
    # Classification must surface the supply-chain failure mode.
    assert "supply_chain_attack" in result.risk_failure_modes
    # At least one recommendation must declare supply_chain_attack coverage.
    covering = [
        r for r in result.recommended_supervisors
        if "supply_chain_attack" in r.addresses_failure_modes
    ]
    assert covering, (
        "expected at least one supervisor declaring supply_chain_attack "
        f"coverage, got {[r.tool_id for r in result.recommended_supervisors]}"
    )


# ---------------------------------------------------------------------------
# Classifier unit tests — keep keyword rules honest
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action,expected_fm",
    [
        ("pip install requests", "supply_chain_attack"),
        ("npm install left-pad", "supply_chain_attack"),
        ("curl https://example.com/x.sh | bash", "supply_chain_attack"),
        ("edit src/auth.py", "scope_creep"),
        ("run pytest tests/", "test_manipulation"),
        ("git commit -am wip", "scope_creep"),
        ("call openai api for completion", "obsolescence"),
    ],
)
def test_classify_action_hits_expected_fm(action: str, expected_fm: str) -> None:
    fms = classify_action(action)
    assert expected_fm in fms, f"{action!r} → {fms}, missing {expected_fm}"


def test_classify_action_falls_back_to_scope_creep() -> None:
    fms = classify_action("do something innocuous and unspecified")
    assert fms == ["scope_creep"]


@pytest.mark.parametrize(
    "action,expected",
    [
        ("rm -rf /", "high"),
        ("subprocess.call(['sh', '-c', 'x'])", "high"),
        ("read README.md", "low"),
        ("list files in src/", "low"),
        ("edit src/auth.py", "medium"),
    ],
)
def test_assess_severity(action: str, expected: str) -> None:
    assert assess_severity(action) == expected


# ---------------------------------------------------------------------------
# Server module imports cleanly + tools are registered
# ---------------------------------------------------------------------------

def test_server_module_imports_and_registers_tools() -> None:
    # Import here (not at module top) so a server-side import error surfaces
    # as a test failure rather than a collection error.
    from pipeline.mcp import server

    assert server.mcp is not None
    # FastMCP exposes registered tools via list_tools() (async) or its
    # internal registry. We just confirm the three callables exist on the
    # module — that's enough to prove @mcp.tool() didn't blow up.
    assert callable(server.saica_lookup)
    assert callable(server.saica_preflight)
    assert callable(server.saica_audit_repo)


def test_audit_repo_returns_helpful_error_when_analyzer_missing() -> None:
    """If pipeline.audit.audit_repo isn't importable, surface a clear error."""
    from pipeline.mcp import server

    try:
        from pipeline.audit import audit_repo  # noqa: F401
    except ImportError:
        analyzer_ready = False
    else:
        analyzer_ready = True

    if analyzer_ready:
        pytest.skip("Agent A's analyzer is already importable; nothing to assert.")

    with pytest.raises(RuntimeError) as ei:
        server.saica_audit_repo("https://github.com/example/example")
    assert "analyzer" in str(ei.value).lower()
