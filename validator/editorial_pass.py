#!/usr/bin/env python3
"""Editorial enrichment for the 30 auto-graduated papers.

Replaces the placeholder ``Auto-graduated`` notes blocks with proper
hand-curation-quality editorial notes that:

  1. Name the paper's specific contribution.
  2. Name the specific tools / datasets / repos it studies (these mentions
     feed the citation backfill at tool-id resolution time).
  3. Map the paper to SAICA-KG's 11 failure modes using snake_case ids
     (so the FailureMode-level citation backfill picks them up).
  4. Briefly note how the findings could inform supervision strategy.

Only modifies the ``notes`` field. Uses ruamel.yaml to preserve order,
quoting, comments, and blank lines (per the
``validator/bulk_annotate_surfaces.py`` convention).

Run:

    .venv/bin/python -m validator.editorial_pass            # write
    .venv/bin/python -m validator.editorial_pass --dry      # preview
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.scalarstring import FoldedScalarString  # noqa: E402

PAPERS_DIR = REPO / "data" / "papers"
REPORT_PATH = REPO / "validator" / "editorial_pass.report.md"

# Wrap width for notes-block lines (matches graduate_papers.py _block_scalar
# convention of ~76 cols).
_NOTES_WRAP_COLS = 76


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _refold_notes_block(text: str) -> str:
    """Find the ``notes: >-`` (or ``notes: >``) block in ``text`` and rewrap
    its body at ``_NOTES_WRAP_COLS`` columns under a ``notes: >`` header,
    matching the existing hand-curated paper convention.

    The block scalar is single-paragraph (no blank lines), so we collapse
    whitespace and re-wrap.
    """
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # Match "notes: >" or "notes: >-" or "notes: >+" (ignore indentation:
        # paper-level notes are always at top level / col 0)
        stripped = line.lstrip()
        indent_len = len(line) - len(stripped)
        if (
            indent_len == 0
            and stripped.startswith("notes:")
            and stripped[len("notes:"):].lstrip().startswith(">")
        ):
            # Collect body lines: any subsequent line that is empty or
            # indented more than 0 cols. (notes is the last field in our
            # papers, but be defensive.)
            j = i + 1
            body_lines: list[str] = []
            body_indent = None
            while j < n:
                bl = lines[j]
                if bl.strip() == "":
                    body_lines.append("")
                    j += 1
                    continue
                bl_indent = len(bl) - len(bl.lstrip())
                if bl_indent == 0:
                    break
                if body_indent is None:
                    body_indent = bl_indent
                body_lines.append(bl[body_indent:])
                j += 1
            # Collapse and re-wrap the body. Folded-scalar semantics: blank
            # lines become paragraph breaks; otherwise whitespace collapses.
            joined = " ".join(s.strip() for s in body_lines if s.strip() != "")
            wrapped = _wrap(joined, _NOTES_WRAP_COLS)
            out.append("notes: >")
            for w in wrapped:
                out.append("  " + w)
            i = j
            continue
        out.append(line)
        i += 1
    # Preserve the original trailing-newline behavior.
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + suffix


def _wrap(text: str, cols: int) -> list[str]:
    """Greedy word wrap at ``cols`` columns. Handles long unbreakable tokens
    by letting them overflow rather than splitting them.
    """
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= cols:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Hand-curated notes for each of the 30 auto-graduated papers.
#
# Schema for each entry:
#   notes:        the new prose (will be written as a folded block scalar)
#   modes:        list of SAICA failure-mode snake_case ids the notes mention
#   tools:        list of tool / dataset / repo names cited in the abstract
# ---------------------------------------------------------------------------

ENTRIES: dict[str, dict[str, object]] = {
    "ashrafi-2025-enhancing-llm-code-generation": {
        "notes": (
            "Empirical study chaining multi-agent collaboration with"
            " runtime-execution-information-based debugging across 19 LLMs on"
            " HumanEval and MBPP, measuring functional accuracy, reliability,"
            " and generation latency. Useful as evidence that runtime"
            " feedback loops (a post-generation supervision pattern) reduce"
            " logic_error rates over single-shot generation, but also as"
            " evidence that naive chaining inflates latency. Relates to"
            " SAICA-KG failure modes: logic_error, incomplete_execution."
            " Informs the post_generation TemporalPhase axis: runtime-debug"
            " agents act as a self-correcting layer that shifts where"
            " supervision catches faults."
        ),
        "modes": ["logic_error", "incomplete_execution"],
        "tools": ["HumanEval", "MBPP"],
    },
    "atri-2025-trustworthy-agentic-ai-balancing": {
        "notes": (
            "Pattern paper proposing a trustworthy-agentic-AI architecture"
            " built from a policy gate, typed tools and effects,"
            " human-in-the-loop (HITL) controls, layered safety monitors, and"
            " evidence logs, aligned to NIST AI RMF, ISO/IEC 42001, and the"
            " EU AI Act. Light on empirical content but useful as a"
            " supervision-vocabulary anchor for SAICA-KG's ControlParadigm"
            " (policy gate, HITL) and TemporalPhase (real-time monitor vs."
            " ex-post evidence log) partitions. Relates to SAICA-KG failure"
            " modes: scope_creep, security_vulnerability,"
            " incomplete_execution. Cite for the typed-effects framing when"
            " arguing that supervision must be explicit at the tool"
            " boundary."
        ),
        "modes": ["scope_creep", "security_vulnerability", "incomplete_execution"],
        "tools": [],
    },
    "bhattarai-2025-arcs-agentic-retrieval-augmented": {
        "notes": (
            "Introduces ARCS (Agentic Retrieval-Augmented Code Synthesis), a"
            " budgeted synthesize-execute-repair loop over a frozen LLM with"
            " formal guarantees on termination, monotonic improvement, and"
            " bounded cost. Evaluated on HumanEval, TransCoder, and a LANL"
            " scientific corpus; reports 87.2% pass@1 on HumanEval with"
            " Llama-3.1-405B vs. CodeAgent at 82.3%. The"
            " retrieval-before-generation design is a concrete example of a"
            " pre_generation guardrail that targets fabrication. Relates to"
            " SAICA-KG failure modes: fabrication, logic_error. Useful as a"
            " case study for the ControlParadigm axis: a tiered controller"
            " (Small/Medium/Large) is a worked example of cost-aware"
            " supervision."
        ),
        "modes": ["fabrication", "logic_error"],
        "tools": ["HumanEval", "TransCoder", "Llama-3.1-405B", "CodeAgent", "CoderEval", "RepoExec"],
    },
    "bulut-2026-avda-autonomous-vibe-detection": {
        "notes": (
            "Introduces AVDA, an MCP-based framework for automating"
            " cybersecurity detection authoring by feeding organizational"
            " context (existing detections, telemetry schemas, style guides)"
            " into AI-assisted code generation. Compares Baseline,"
            " Sequential, and Agentic workflows; reports a 19% similarity"
            " uplift for Agentic over Baseline at 40x higher token cost than"
            " Sequential. Notable failure pattern: 8.9% exclusion-parity"
            " score (the agent struggles to honor explicit"
            " not-this-detection constraints) — a clear instance of"
            " scope_creep when the agent is pointed at security telemetry."
            " Relates to SAICA-KG failure modes: scope_creep,"
            " context_pollution. Useful as MCP integration evidence and as a"
            " worked example of how organizational context becomes"
            " supervision substrate."
        ),
        "modes": ["scope_creep", "context_pollution"],
        "tools": ["MCP", "Model Context Protocol"],
    },
    "gao-2026-skillreducer-optimizing-llm-agent": {
        "notes": (
            "Large-scale empirical study of 55,315 publicly available agent"
            " skills (pre-packaged instruction sets) finding systemic"
            " inefficiencies: 26.4% lack routing descriptions, over 60% of"
            " body content is non-actionable, and reference files inject"
            " tens of thousands of tokens per invocation. Proposes"
            " SkillReducer, a two-stage compression framework evaluated on"
            " 600 skills and the SkillsBench benchmark, achieving 48%"
            " description and 39% body compression while improving"
            " functional quality by 2.8%. The 'less-is-more' finding"
            " directly evidences context_pollution as a supervision-relevant"
            " failure mode. Relates to SAICA-KG failure modes:"
            " context_pollution, scope_creep. Useful for arguing that"
            " context curation is a first-class supervision activity, not"
            " just a cost optimization."
        ),
        "modes": ["context_pollution", "scope_creep"],
        "tools": ["SkillsBench"],
    },
    "gu-2025-retrieve-effective-retrieval-augmented": {
        "notes": (
            "Empirical study of which retrieved-information sources actually"
            " help repository-level code generation. Key finding: in-context"
            " code and potential API information help, but retrieved"
            " similar-code snippets often introduce noise that degrades"
            " results by up to 15%. Proposes AllianceCoder with"
            " chain-of-thought decomposition and semantic-description API"
            " retrieval; evaluated on CoderEval and RepoExec with up to 20%"
            " Pass@1 improvement. Direct evidence that uncurated RAG context"
            " is a context_pollution vector. Relates to SAICA-KG failure"
            " modes: context_pollution, dependency_blindness. Cite when"
            " arguing that retrieval-quality is itself a supervisable"
            " surface."
        ),
        "modes": ["context_pollution", "dependency_blindness"],
        "tools": ["CoderEval", "RepoExec", "AllianceCoder"],
    },
    "horikawa-2025-agentic-refactoring-empirical-study": {
        "notes": (
            "Large-scale empirical study of agentic refactoring on the AIDev"
            " dataset: 15,451 refactoring instances across 12,256 PRs and"
            " 14,988 commits in real-world open-source Java projects, with"
            " agents (OpenAI Codex, Claude Code, Cursor named) targeting"
            " refactoring in 26.1% of commits. Finds agentic refactoring is"
            " dominated by low-level consistency edits (rename"
            " variable/parameter, change variable type) rather than the"
            " high-level design changes humans favor — a behavioral"
            " signature relevant to scope_creep (over-eager local edits) and"
            " incomplete_execution (rarely finishes a real architectural"
            " refactor). Relates to SAICA-KG failure modes: scope_creep,"
            " incomplete_execution. Primary citation for what agentic edits"
            " actually look like in production today."
        ),
        "modes": ["scope_creep", "incomplete_execution"],
        "tools": ["OpenAI Codex", "Claude Code", "Cursor", "AIDev"],
    },
    "krishnan-2025-advancing-multi-agent-systems": {
        "notes": (
            "Architectural framework paper proposing standardized context"
            " sharing and coordination mechanisms over the Model Context"
            " Protocol (MCP) for multi-agent systems. Mostly theoretical"
            " (case studies in enterprise knowledge management,"
            " collaborative research, and distributed problem-solving) but"
            " useful as an MCP-vocabulary anchor for SAICA-KG's tool-layer"
            " nodes. Relates to SAICA-KG failure modes: context_pollution,"
            " cascading_failure. Cite when discussing how MCP is intended to"
            " constrain context-sharing and where its design intent diverges"
            " from observed practice."
        ),
        "modes": ["context_pollution", "cascading_failure"],
        "tools": ["MCP", "Model Context Protocol"],
    },
    "haque-2025-secure-suspect-investigating-package": {
        "notes": (
            "First systematic empirical study of how quantization (8-bit and"
            " 4-bit vs. full-precision) affects package hallucination and"
            " vulnerability rates in LLM-generated Go install commands."
            " Evaluates five Qwen model sizes across SO, MBPP, and"
            " paraphrase datasets; finds quantization substantially"
            " increases the package hallucination rate (PHR), with 4-bit"
            " degrading most, and that vulnerability presence rate (VPR)"
            " among correctly-generated packages also rises as precision"
            " decreases. Most fabricated packages resemble realistic"
            " URL-based Go module paths (malformed GitHub or golang.org"
            " repositories) — a slopsquatting-adjacent supply-chain risk."
            " Relates to SAICA-KG failure modes: supply_chain_attack,"
            " fabrication, dependency_blindness, security_vulnerability."
            " Cite as evidence that deployment-time decisions (quantization)"
            " materially shift FailureMode distributions."
        ),
        "modes": ["supply_chain_attack", "fabrication", "dependency_blindness", "security_vulnerability"],
        "tools": ["Qwen", "MBPP", "GitHub"],
    },
    "fan-2025-mcptoolbench-large-scale-ai": {
        "notes": (
            "Introduces MCPToolBench++, a large-scale multi-domain MCP tool"
            " use benchmark built on a marketplace of over 4k MCP servers"
            " across 40+ categories collected from MCP marketplaces and"
            " GitHub. Datasets include single-step and multi-step tool calls"
            " evaluated against SOTA agentic LLMs. Notable for explicitly"
            " calling out two SAICA-relevant pressures: (a) real-world MCP"
            " server success rates are not guaranteed and vary across"
            " servers (incomplete_execution), and (b) the LLM context window"
            " caps the number of available tools that can be called in a"
            " single run because tool descriptions are long-token"
            " (context_pollution). Relates to SAICA-KG failure modes:"
            " context_pollution, incomplete_execution. Cite as the canonical"
            " MCP tool-use evaluation harness."
        ),
        "modes": ["context_pollution", "incomplete_execution"],
        "tools": ["MCP", "Model Context Protocol", "GitHub", "MCPToolBench"],
    },
    "li-2025-netmcp-network-aware-model": {
        "notes": (
            "Builds NetMCP, an experimental MCP testbed over five"
            " representative network states, and proposes SONAR (Semantic"
            " Oriented and Network Aware Routing), an MCP tool-routing"
            " algorithm that jointly optimizes semantic similarity and"
            " network QoS. Demonstrates that semantic-only routing leaves"
            " task success and latency on the table when MCP servers degrade"
            " or fail. Relates to SAICA-KG failure modes:"
            " incomplete_execution, cascading_failure. Useful as a"
            " production-engineering anchor: even when the agent reasons"
            " correctly, infrastructure-layer faults propagate as"
            " task-level failures, which informs the supervision boundary"
            " between tool-call layer and agent layer. Code at"
            " github.com/NICE-HKU/NetMCP."
        ),
        "modes": ["incomplete_execution", "cascading_failure"],
        "tools": ["MCP", "Model Context Protocol", "NetMCP", "SONAR"],
    },
    "kota-2025-zero-trust-security-frameworks": {
        "notes": (
            "Position paper proposing a Zero-Trust Architecture (ZTA)"
            " framework for MCP server communications, covering identity"
            " and device verification, mutual authentication,"
            " micro-segmentation, dynamic policy enforcement, continuous"
            " monitoring, and breach containment. Names MCP-specific threat"
            " surfaces: client-server interactions, tool invocations,"
            " context leakage, and lateral movement. Relates to SAICA-KG"
            " failure modes: security_vulnerability, supply_chain_attack."
            " Useful as a vocabulary anchor for the security-layer Tool"
            " nodes; light on empirical evidence so cite as theoretical"
            " framing rather than primary measurement."
        ),
        "modes": ["security_vulnerability", "supply_chain_attack"],
        "tools": ["MCP", "Model Context Protocol"],
    },
    "he-2025-automatic-red-teaming-llm": {
        "notes": (
            "Proposes AutoMalTool, an automated red-teaming framework that"
            " generates malicious MCP tools capable of manipulating the"
            " behavior of mainstream LLM-based agents while evading current"
            " detection mechanisms. The first systematic (rather than"
            " proof-of-concept) treatment of MCP tool-poisoning attacks."
            " Direct evidence that the MCP integration surface is a"
            " supply_chain_attack vector and that detection-mechanism gaps"
            " are exploitable. Relates to SAICA-KG failure modes:"
            " supply_chain_attack, security_vulnerability. Cite alongside"
            " spracklen-2024 and the MCP-Guard / MSB benchmarks when arguing"
            " that supply-chain awareness must extend to MCP tool"
            " marketplaces, not just package registries."
        ),
        "modes": ["supply_chain_attack", "security_vulnerability"],
        "tools": ["MCP", "Model Context Protocol", "AutoMalTool"],
    },
    "li-2026-security-considerations-artificial-intelligence": {
        "notes": (
            "Lightly-adapted version of Perplexity's response to NIST/CAISI"
            " RFI 2025-0035 on frontier AI agent security. Maps principal"
            " attack surfaces across tools, connectors, hosting boundaries,"
            " and multi-agent coordination, with explicit emphasis on"
            " indirect prompt injection, confused-deputy behavior, and"
            " cascading failures in long-running workflows. Assesses"
            " defenses as a layered stack: input/model-level mitigations,"
            " sandboxed execution, and deterministic policy enforcement for"
            " high-consequence actions. Relates to SAICA-KG failure modes:"
            " security_vulnerability, cascading_failure,"
            " supply_chain_attack. Useful as an industry-perspective anchor"
            " for the layered-defense framing in SAICA-KG's ControlParadigm"
            " axis."
        ),
        "modes": ["security_vulnerability", "cascading_failure", "supply_chain_attack"],
        "tools": ["NIST"],
    },
    "krishna-2025-importing-phantoms-measuring-llm": {
        "notes": (
            "Measures package-hallucination behavior across multiple LLMs"
            " and programming languages. Two key empirical claims for"
            " SAICA-KG: (a) the Pareto frontier between code-generation"
            " performance and package-hallucination rate is sparsely"
            " populated, suggesting coding models are not currently"
            " optimized for secure code, and (b) there is an inverse"
            " correlation between package-hallucination rate and HumanEval"
            " performance, offering a heuristic for forecasting which"
            " models are most exposed. Relates to SAICA-KG failure modes:"
            " supply_chain_attack, fabrication, security_vulnerability."
            " Cite as a complement to spracklen-2024 — same problem,"
            " different measurement angle."
        ),
        "modes": ["supply_chain_attack", "fabrication", "security_vulnerability"],
        "tools": ["HumanEval"],
    },
    "liu-2025-empirical-study-failures-automated": {
        "notes": (
            "Manual analysis of 150 failed SWE-Bench-Verified instances"
            " across three SOTA tools (pipeline-based and agentic)"
            " produces a taxonomy of 3 phases, 9 main categories, and 25"
            " fine-grained failure subcategories. Key finding: agentic"
            " failures are dominated by flawed reasoning and 'cognitive"
            " deadlocks' — distinct failure fingerprints from"
            " pipeline-based tools. Proposes a collaborative"
            " Expert-Executor framework where a supervisory Expert agent"
            " provides strategic oversight and course-correction, solving"
            " 22.2% of previously intractable issues. Strong primary"
            " citation for SAICA-KG's logic_error and"
            " incomplete_execution modes; the cognitive-deadlock finding"
            " is direct evidence for incomplete_execution. Relates to"
            " SAICA-KG failure modes: logic_error, incomplete_execution,"
            " cascading_failure."
        ),
        "modes": ["logic_error", "incomplete_execution", "cascading_failure"],
        "tools": ["SWE-Bench", "SWE-Bench-Verified"],
    },
    "li-2025-glue-code-protocols-critical": {
        "notes": (
            "Critical analysis of integrating Google's Agent-to-Agent (A2A)"
            " protocol with Anthropic's Model Context Protocol (MCP). Names"
            " the emergent risk surfaces at the A2A+MCP intersection:"
            " semantic interoperability between agent tasks and tool"
            " capabilities, compounded security risks from combined"
            " discovery and execution, debugging difficulties across"
            " protocols, and governance gaps for the 'Agent Economy'."
            " Relates to SAICA-KG failure modes: security_vulnerability,"
            " cascading_failure, scope_creep. Cite as supervision-vocabulary"
            " anchor when discussing inter-agent vs. agent-tool boundaries"
            " in the ControlParadigm axis."
        ),
        "modes": ["security_vulnerability", "cascading_failure", "scope_creep"],
        "tools": ["MCP", "Model Context Protocol", "A2A"],
    },
    "piao-2025-agentbay-hybrid-interaction-sandbox": {
        "notes": (
            "Introduces AgentBay, a sandbox service providing isolated"
            " execution environments across Windows, Linux, Android, web"
            " browsers, and code interpreters with a hybrid"
            " AI-or-human control interface (MCP / SDK programmatic access"
            " for agents; seamless human takeover via an Adaptive Streaming"
            " Protocol). Reports >48% success-rate improvement on complex"
            " tasks for the Agent+Human model. Direct evidence that"
            " HITL-with-low-friction-takeover is a measurable supervision"
            " lever. Relates to SAICA-KG failure modes: incomplete_execution,"
            " scope_creep. Useful as a Tool-node citation for the sandbox"
            " category and as evidence that the human-takeover latency"
            " budget is itself a supervision design parameter (echoing"
            " Lindner-2025's sync/semi-sync/async axis)."
        ),
        "modes": ["incomplete_execution", "scope_creep"],
        "tools": ["MCP", "Model Context Protocol", "AgentBay"],
    },
    "liu-2025-code-copycat-conundrum-demystifying": {
        "notes": (
            "First empirical study of code repetition across 19 SOTA code"
            " LLMs on three benchmarks; produces a 20-pattern taxonomy of"
            " repetition at character, statement, and block granularity."
            " Proposes DeRep, a rule-based detect-and-mitigate technique"
            " that delivers large repetition reductions and a 208.3% Pass@1"
            " uplift over greedy search. Repetition is a concrete signature"
            " of context_pollution (the model echoing its own context) and"
            " of degraded logic_error patterns (e.g. duplicated branches"
            " hiding bugs). Relates to SAICA-KG failure modes:"
            " context_pollution, logic_error. Cite when arguing that"
            " syntactic-quality detectors complement semantic ones in the"
            " supervision stack."
        ),
        "modes": ["context_pollution", "logic_error"],
        "tools": ["DeRep"],
    },
    "liu-2026-packmonitor-enabling-zero-package": {
        "notes": (
            "Introduces PackMonitor, a decoding-time monitor that"
            " eliminates (not just mitigates) package hallucinations by"
            " constraining the decoding space to an authoritative package"
            " list when the agent is generating an install command. Three"
            " mechanisms: a Context-Aware Parser that triggers intervention"
            " only during install-command generation, a Package-Name"
            " Intervenor that restricts decoding, and a DFA-Caching"
            " mechanism that scales to millions of packages. Tested on five"
            " widely used LLMs, drives package-hallucination rate to zero"
            " with negligible latency overhead. Direct demonstration that"
            " in_generation TemporalPhase supervision can fully prevent a"
            " specific FailureMode. Relates to SAICA-KG failure modes:"
            " supply_chain_attack, fabrication, dependency_blindness."
            " Strong primary cite for the in_generation phase of the"
            " TemporalPhase axis."
        ),
        "modes": ["supply_chain_attack", "fabrication", "dependency_blindness"],
        "tools": ["PackMonitor"],
    },
    "song-2025-help-hurdle-rethinking-model": {
        "notes": (
            "Introduces MCPGAUGE, the first comprehensive evaluation"
            " framework for LLM-MCP interactions along four dimensions:"
            " proactivity (self-initiated tool use), compliance (adherence"
            " to tool-use instructions), effectiveness (task performance"
            " post-integration), and overhead (computational cost). 160-"
            " prompt suite across 25 datasets covering knowledge"
            " comprehension, general reasoning, and code generation;"
            " evaluated on six commercial LLMs and 30 MCP tool suites with"
            " ~20,000 API calls. Findings challenge the prevailing"
            " assumption that MCP integration unambiguously helps. Relates"
            " to SAICA-KG failure modes: scope_creep, context_pollution,"
            " incomplete_execution. Cite as evidence that 'tool use' itself"
            " is a supervisable behavior, not just a capability."
        ),
        "modes": ["scope_creep", "context_pollution", "incomplete_execution"],
        "tools": ["MCP", "Model Context Protocol", "MCPGAUGE"],
    },
    "twist-2025-library-hallucinations-llms-risk": {
        "notes": (
            "First systematic study of how user-level prompt variations"
            " impact library hallucinations in LLM-generated code. Evaluates"
            " seven LLMs across two hallucination types — library-name"
            " hallucinations (invalid imports) and library-member"
            " hallucinations (invalid calls from valid libraries) — using"
            " realistic developer-forum language and controlled"
            " misspelling/fake-name perturbations. Striking findings:"
            " one-character misspellings trigger hallucinations in up to"
            " 26% of tasks, fake library names are accepted in up to 99% of"
            " tasks, and time-related prompts hallucinate in up to 84% of"
            " tasks (an obsolescence signal). Relates to SAICA-KG failure"
            " modes: fabrication, supply_chain_attack, obsolescence,"
            " dependency_blindness. The fake-name acceptance rate is a"
            " direct slopsquatting attack vector."
        ),
        "modes": ["fabrication", "supply_chain_attack", "obsolescence", "dependency_blindness"],
        "tools": [],
    },
    "ni-2025-viscoder2-building-multi-language"
    : {
        "notes": (
            "Releases three resources for visualization-coding agents:"
            " VisCode-Multi-679K (679K validated executable visualization"
            " samples with multi-turn correction dialogues across 12"
            " languages), VisPlotBench (an executable benchmark with"
            " single-shot and multi-round self-debug protocols), and"
            " VisCoder2 (a model family trained on the dataset). Reports"
            " 82.4% overall execution pass rate at 32B with iterative"
            " self-debug, particularly in symbolic and"
            " compiler-dependent languages. Useful as a worked example of"
            " how iterative self-debug closes the gap on logic_error and"
            " incomplete_execution failures, and as a Tool-node citation"
            " for the visualization-coding subdomain. Relates to SAICA-KG"
            " failure modes: logic_error, incomplete_execution."
        ),
        "modes": ["logic_error", "incomplete_execution"],
        "tools": ["VisCoder2", "VisCode-Multi-679K", "VisPlotBench", "GPT-4.1"],
    },
    "qiu-2026-prbench-end-end-paper": {
        "notes": (
            "Introduces PRBench, a benchmark of 30 expert-curated"
            " end-to-end physics paper-reproduction tasks across 11"
            " subfields, where the agent must comprehend a paper, implement"
            " its algorithms from scratch, and produce quantitative results"
            " matching the original publication. The best-performing agent"
            " (OpenAI Codex powered by GPT-5.3-Codex) achieves only 34%"
            " mean overall score, with a zero end-to-end callback success"
            " rate. Authors identify systematic failure modes including"
            " errors in formula implementation, inability to debug numerical"
            " simulations, and fabrication of output data — all directly"
            " on-model for SAICA-KG. Relates to SAICA-KG failure modes:"
            " fabrication, logic_error, incomplete_execution. Cite when"
            " arguing that long-horizon reproducibility is currently the"
            " hardest stress test for coding agents."
        ),
        "modes": ["fabrication", "logic_error", "incomplete_execution"],
        "tools": ["OpenAI Codex", "PRBench"],
    },
    "xing-2025-mcp-guard-multi-stage": {
        "notes": (
            "Proposes MCP-GUARD, a three-stage layered defense for LLM-tool"
            " interactions over MCP: lightweight static scanning for overt"
            " threats, a deep neural detector for semantic attacks, and a"
            " fine-tuned E5-based model achieving 96.01% accuracy on"
            " adversarial-prompt detection, with an LLM arbitrator for the"
            " final decision. Releases MCP-AttackBench, a 70,448-sample"
            " benchmark generated with GPT-4 that simulates real-world"
            " attack vectors circumventing conventional defenses. Relates to"
            " SAICA-KG failure modes: security_vulnerability,"
            " supply_chain_attack. Cite as a layered-defense Tool-node and"
            " as one of the better-grounded MCP-defense benchmarks."
        ),
        "modes": ["security_vulnerability", "supply_chain_attack"],
        "tools": ["MCP", "Model Context Protocol", "MCP-Guard", "MCP-AttackBench", "GPT-4"],
    },
    "santos-2025-decoding-configuration-ai-coding": {
        "notes": (
            "Empirical study of 328 configuration files from public Claude"
            " Code projects, analyzing the software-engineering concerns"
            " they encode (architectural constraints, coding practices, tool"
            " usage policies) and how those concerns co-occur. Provides"
            " concrete evidence that agent configuration files are a"
            " primary supervision substrate in current practice — they are"
            " where humans pre-emptively constrain agent behavior. Relates"
            " to SAICA-KG failure modes: scope_creep, context_pollution."
            " Useful as a primary cite for the pre_generation TemporalPhase"
            " axis (configuration as ex-ante supervision) and as evidence"
            " for why a Claude Code-specific Tool node is warranted."
        ),
        "modes": ["scope_creep", "context_pollution"],
        "tools": ["Claude Code"],
    },
    "zhao-2025-hfuzzer-testing-large-language": {
        "notes": (
            "Proposes HFuzzer, a phrase-based fuzzing framework that"
            " systematically tests LLMs for package hallucinations by"
            " seeding the fuzzer with phrases drawn from package metadata"
            " or coding tasks. Across multiple LLMs HFuzzer triggers"
            " package hallucinations in every model tested and identifies"
            " 2.60x more unique hallucinated packages than mutational"
            " fuzzing baselines; against GPT-4o it surfaces 46 unique"
            " hallucinated packages and shows hallucinations occur not just"
            " during code generation but also during environment"
            " configuration. Relates to SAICA-KG failure modes:"
            " supply_chain_attack, fabrication, security_vulnerability."
            " Cite as a fuzzing-style measurement tool that complements"
            " static prevalence studies (Spracklen-2024, Krishna-2025)."
        ),
        "modes": ["supply_chain_attack", "fabrication", "security_vulnerability"],
        "tools": ["HFuzzer", "GPT-4o"],
    },
    "zhang-2025-mcp-security-bench-msb": {
        "notes": (
            "Introduces MSB (MCP Security Benchmark), the first end-to-end"
            " evaluation suite that measures LLM-agent resistance to"
            " MCP-specific attacks across the full tool-use pipeline (task"
            " planning, tool invocation, response handling). Contributes a"
            " 12-attack taxonomy (name-collision, preference manipulation,"
            " prompt injections in tool descriptions, out-of-scope parameter"
            " requests, user-impersonating responses, false-error"
            " escalation, tool-transfer, retrieval injection, mixed"
            " attacks), an evaluation harness that runs real benign and"
            " malicious tools via MCP rather than simulation, and the Net"
            " Resilient Performance (NRP) robustness metric. Evaluates nine"
            " popular LLM agents across 10 domains and 405 tools (2,000"
            " attack instances); finds that stronger models are more"
            " vulnerable due to better instruction following. Relates to"
            " SAICA-KG failure modes: security_vulnerability,"
            " supply_chain_attack, scope_creep. Strong primary cite for the"
            " MCP-security FailureMode cluster. Code at"
            " github.com/dongsenzhang/MSB."
        ),
        "modes": ["security_vulnerability", "supply_chain_attack", "scope_creep"],
        "tools": ["MCP", "Model Context Protocol", "MSB", "MCP Security Benchmark", "GitHub"],
    },
    "wang-2025-ai-agentic-programming-survey": {
        "notes": (
            "Survey of AI agentic programming: introduces a taxonomy of"
            " agent behaviors and system architectures and reviews"
            " techniques for planning, context management, tool integration,"
            " execution monitoring, and benchmarking datasets. Useful as a"
            " coverage map for SAICA-KG's relationship to the wider"
            " coding-agent literature; broad rather than deep. Relates to"
            " SAICA-KG failure modes: logic_error, context_pollution,"
            " incomplete_execution. Cite when situating SAICA-KG against"
            " the survey landscape rather than against a primary"
            " measurement paper."
        ),
        "modes": ["logic_error", "context_pollution", "incomplete_execution"],
        "tools": [],
    },
    "zhang-2025-semanticforge-repository-level-code": {
        "notes": (
            "Proposes SemanticForge, a repository-level code-generation"
            " framework that targets two failure modes the authors name"
            " explicitly: 'logical hallucination' (incorrect"
            " control/data-flow reasoning, ~ SAICA's logic_error) and"
            " 'schematic hallucination' (type mismatches, signature"
            " violations, architectural inconsistencies, ~ a mix of"
            " logic_error and dependency_blindness). The fix combines a"
            " heterogeneous repository knowledge graph (static + dynamic"
            " traces), neural query planners, SMT-guided beam search for"
            " constraint satisfaction, and incremental graph updates."
            " Reports 49.8% Pass@1 with 52% reduction in schematic"
            " hallucination and 31% reduction in logical hallucination on"
            " a 4,250-task benchmark across 50 Python projects. Relates to"
            " SAICA-KG failure modes: fabrication, logic_error,"
            " dependency_blindness. Cite as a peer example of using a"
            " knowledge graph as a supervision substrate — directly"
            " relevant to SAICA-KG's own architecture argument."
        ),
        "modes": ["fabrication", "logic_error", "dependency_blindness"],
        "tools": ["SemanticForge", "SMT"],
    },
}


def update_notes(path: Path, *, yaml: YAML, dry: bool) -> tuple[str, dict]:
    """Update the ``notes`` field of one paper YAML.

    Returns ``(action, info)`` where ``info`` carries the original notes,
    new notes, modes, and tools for the report.
    """
    paper_id = path.stem
    entry = ENTRIES.get(paper_id)
    if entry is None:
        return ("skipped_not_in_pass", {"paper_id": paper_id})

    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.load(fh)
    if doc is None:
        return ("skipped_empty_yaml", {"paper_id": paper_id})

    original_notes = doc.get("notes")
    new_notes_text = entry["notes"]
    # Use folded scalar (>) so dump matches the existing convention.
    new_notes_value = FoldedScalarString(new_notes_text)

    info = {
        "paper_id": paper_id,
        "original_notes": str(original_notes or "").strip(),
        "new_notes": new_notes_text,
        "modes": entry["modes"],
        "tools": entry["tools"],
    }

    if dry:
        return ("preview", info)

    doc["notes"] = new_notes_value

    buf = io.StringIO()
    yaml.dump(doc, buf)
    new_text = buf.getvalue()
    new_text = _refold_notes_block(new_text)
    old_text = path.read_text(encoding="utf-8")
    if new_text == old_text:
        return ("noop", info)
    path.write_text(new_text, encoding="utf-8")
    return ("wrote", info)


def write_report(report_path: Path, results: list[tuple[str, dict]]) -> None:
    lines: list[str] = []
    lines.append("# editorial_pass report")
    lines.append("")
    lines.append(
        "Editorial enrichment of the 30 auto-graduated papers. Replaces the"
        " generic `Auto-graduated from candidate pool; review the editorial"
        " framing before promoting to a primary cite.` placeholder notes"
        " (written by `validator/graduate_papers.py`) with hand-curated"
        " editorial notes that name specific tools / datasets / methods and"
        " explicitly tag SAICA-KG failure modes by snake_case id."
    )
    lines.append("")
    lines.append(
        "If this script is re-run, the `Original notes` section of each"
        " entry will show the previously-written editorial notes, not the"
        " original auto-graduated placeholder. The original placeholder"
        " followed the template `Relates to SAICA-KG failure modes: <list> |"
        " Auto-graduated from candidate pool; review the editorial framing"
        " before promoting to a primary cite. Source: <s2|elicit>:<query>.`"
    )
    lines.append("")
    counts: dict[str, int] = {}
    for action, _ in results:
        counts[action] = counts.get(action, 0) + 1
    for k, v in sorted(counts.items()):
        lines.append(f"- {k}: {v}")
    total_modes = sum(len(info.get("modes", [])) for _, info in results if info)
    total_tools = sum(len(info.get("tools", [])) for _, info in results if info)
    substantial = sum(
        1 for _, info in results if info and len(info.get("new_notes", "")) >= 600
    )
    minimal = sum(
        1 for _, info in results
        if info and 0 < len(info.get("new_notes", "")) < 600
    )
    lines.append(f"- Total FM mode mentions: {total_modes}")
    lines.append(f"- Total tool / dataset names extracted: {total_tools}")
    lines.append(f"- Papers with substantial new content (>= 600 chars): {substantial}")
    lines.append(f"- Papers with minimal new content (< 600 chars): {minimal}")
    lines.append("")
    lines.append("## Per-paper diffs")
    lines.append("")
    for action, info in results:
        if not info:
            continue
        pid = info.get("paper_id", "?")
        lines.append(f"### `{pid}` — {action}")
        lines.append("")
        if info.get("modes"):
            lines.append(f"- SAICA modes: {', '.join(info['modes'])}")
        else:
            lines.append("- SAICA modes: _none named_")
        if info.get("tools"):
            lines.append(f"- Tools / datasets named: {', '.join(info['tools'])}")
        else:
            lines.append("- Tools / datasets named: _none extracted_")
        lines.append("")
        lines.append("**Original notes:**")
        lines.append("")
        lines.append("> " + (info.get("original_notes") or "_(empty)_").replace("\n", "\n> "))
        lines.append("")
        lines.append("**New notes:**")
        lines.append("")
        lines.append("> " + info.get("new_notes", "").replace("\n", "\n> "))
        lines.append("")
    report_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="preview only; do not write")
    args = parser.parse_args()

    yaml = _make_yaml()
    results: list[tuple[str, dict]] = []
    for paper_id in sorted(ENTRIES):
        path = PAPERS_DIR / f"{paper_id}.yml"
        if not path.exists():
            results.append(("missing_file", {"paper_id": paper_id, "modes": [], "tools": []}))
            continue
        action, info = update_notes(path, yaml=yaml, dry=args.dry)
        results.append((action, info))
        print(f"  {action:8s} {paper_id}")

    write_report(REPORT_PATH, results)
    print()
    print(f"report -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
