# Retracted incident records

**The five records in this folder are retracted. Do not cite them, restore
them or use them as evidence.** They are kept, not deleted, so that the
retraction can be traced: what was claimed, how it was checked, why it was
withdrawn. The list of removed node ids is `data/TOMBSTONES.yml`.

## What was wrong

Each record said that the Columbia DAPLab post "9 Critical Failure Patterns
of Coding Agents" (Reya Vir, 2026-01-08) reported a specific pattern, cited
the post's URL and was marked `reproducibility: confirmed`. The post does not
contain these patterns.

The post's nine patterns are: Presentation & UI Grounding Mismatch; State
Management Failures; Business Logic Mismatch; Data Management Errors; API &
External Service Integration Failures; Security Vulnerabilities; Repeated
Code; Codebase Awareness & Refactoring Issues; Exception & Error Handling.
It says nothing about agents editing or skipping tests, running `rm -rf` or
a force-push, claiming a task is complete with subtasks undone, or fix
attempts that add new errors.

The records were built on an earlier version of
`data/taxonomies/daplab-9-patterns.yml`. Its nine labels were, by the file's
own note, "paraphrased for seed", and the check against the post that the
note asked for had not been done.

## How it was checked

| When | Who | What |
|---|---|---|
| 2026-08-18 | project session, commit `00422e2` (branch `backup/local-18-commits-2026-11-19`) | Post fetched; taxonomy rebuilt; these five files moved here. The commit was never pushed and was dropped from `main` by a reset on 2026-11-19, which put the records back. |
| 2026-11-21 | review round 2 (`research/review_20261121_r2/kg_data.md`, KG-01) | Live post and the Wayback Machine capture of 2026-01-17 read; both list the nine patterns above. |
| 2026-11-21 | fix round (`research/fixes_20261121/kg_data_1.md`, E1) | Live post (HTTP 200) and the same capture fetched again; headings compared; the post text searched for `rm -rf`, force-push, mock, skip, "complete", "done", "context window", truncat*, deprecat*, non-existent: 0 matches. Records moved here again. |

## Files

| File | Pattern it attributed to the post (not in the post) | Was quoted in (state of 2026-11-21) |
|---|---|---|
| `daplab-cascading-recovery-observation-2026.yml` | "DAP-04 Cascading Error Recovery" | `SKILLS.md` and both `SKILL.md` copies ("Real incident" under cascading failure and under context pollution); `site/src/components/fm/fm.ts` (cascading failure) |
| `daplab-destructive-action-observation-2026.yml` | "DAP-08 Destructive Action" | `SKILLS.md` and both `SKILL.md` copies (scope creep) |
| `daplab-fabricated-references-observation-2026.yml` | "DAP-02 Fabricated References" | `SKILLS.md` and both `SKILL.md` copies (fabrication) |
| `daplab-incomplete-task-execution-observation-2026.yml` | "DAP-01 Incomplete Task Execution" | `SKILLS.md` and both `SKILL.md` copies (incomplete execution); `fm.ts` (incomplete execution) |
| `daplab-silent-test-passing-observation-2026.yml` | "DAP-07 Silent Test-Passing Workaround" | `SKILLS.md` and both `SKILL.md` copies (test manipulation); `fm.ts` (test manipulation); recipe `test-manipulation-resistant-flow` |

The Replit database deletion that the destructive-action record named as an
example is a separate, independently sourced record
(`data/incidents/replit-agent-saastr-database-deletion-2025.yml`) and is not
affected.

## What replaced them

Nothing. A record that says "DAPLab observed pattern X" cannot be corrected
by renaming X, because the claim itself is false. The post is still a useful
source: `data/taxonomies/daplab-9-patterns.yml` now holds its real nine
patterns and `data/crosswalks/daplab-to-saica.yml` maps them to SAICA failure
modes where the text supports it.
