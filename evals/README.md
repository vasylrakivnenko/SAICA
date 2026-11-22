# Checks around the recommender file and the Ask endpoint

Two kinds of check live here. Only the second one tests a model.

## 1. File checks (pytest, no model, no network)

`tests/test_recommendations_file.py` reads the generated
[`recommendations.json`](../recommendations.json) and checks it against the
KG and the benchmark results:

- every `tool_id` is a tool in `data/tools/`;
- every failure-mode id is a file in `data/failure_modes/`;
- no tool is listed for a failure mode on which SAICA-Bench measured it
  below the floor (J 0.25 today), and no archived tool is listed.

```bash
.venv/bin/python -m pytest tests/test_recommendations_file.py -q
```

If one of them fails, regenerate the file first
(`python -m validator.generate_recommendations`).

These checks ran through promptfoo's `echo` provider until 2026-11-21 and
were called a "behavioural gate". They test files, so they are pytest
now. Four of the old checks were dropped because they could not fail or
only restated how the recommender is built.

## 2. Live probes of the Ask endpoint (paid, manual)

Two questions are sent to a running Ask backend and the answers are
checked against the KG: the answer to a scope-creep question must name a
tool the catalog tags for `scope_creep`; the answer to "fabrication vs
obsolescence" must speak of both; neither may cite an id in brackets that
is no node of the KG.

Each probe is a real model call. Start the backend, then:

```bash
.venv/bin/python -m pipeline.webapp          # terminal 1: API on 127.0.0.1:4322

ASK_API=http://127.0.0.1:4322/api/ask \
    .venv/bin/python -m pytest tests/test_ask_live_probe.py -q -rs   # terminal 2
```

Without `ASK_API` the two live tests are **skipped**, and pytest reports
them as skipped. They are not part of any gate.

The same probes can be run through promptfoo
([`promptfooconfig.yaml`](../promptfooconfig.yaml)); promptfoo is only the
runner there. It has no "skipped" result, so without `ASK_API` both tests
fail with the reason "NOT RUN". Pin the promptfoo version you run.

The probe logic is in `_assertions.py` and is itself tested without a
network (`tests/test_ask_live_probe.py`, the tests that are not marked
live).
