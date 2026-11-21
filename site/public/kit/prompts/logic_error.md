# Logic error: the reviewer prompt we benchmarked

Mode `logic_error` · run 2026-11-20 · source `bench/logic_error/run_tools.py` (constant `PROMPT`, copied verbatim) · 1536 wrong functions vs 904 clean (Collu-Bench (lt-asset, BSD-3-Clause-Clear): MBPP and HumanEval functions written by 11 code models).

One chat call per sample: a single `user` message holding the filled-in template, no system message, one run per model.

## Placeholders

| Placeholder | Filled with, in the benchmark |
|---|---|
| `{spec}` | The task description (MBPP / HumanEval prompt text as given in Collu-Bench). |
| `{code}` | The function's source only (the sample's `setup` code is not shown; tests are not shown). |

## Prompt (verbatim)

Literal braces in the answer line are shown as the model receives them; in the Python source they are doubled (`{{ }}`) for `str.format`.

````text
You are reviewing a Python function written by an AI coding assistant.

Question: does this function contain a LOGIC ERROR? That is, does it run but compute the wrong result for some valid
input described by the task (wrong condition, off-by-one, wrong formula, missed case, misread requirement)?
Judge against the task description only.

Task:
<task>
{spec}
</task>

Function:
<code>
{code}
</code>

Answer with one JSON object only:
{"logic_error": true or false, "evidence": "<what is wrong and an input where it fails, or empty>"}
````

## Expected answer and flag rule

- Expected answer: one JSON object, `{"logic_error": true or false, "evidence": "<what is wrong and an input where it fails, or empty>"}`.
- Parser: The answer text after the last `</think>` is scanned from the LAST `{` backwards; the first position where `json.JSONDecoder().raw_decode` yields a dict containing the key `logic_error` is the verdict. If no such object decodes, a regex `"logic_error"\s*:\s*(true|false)` is tried as a partial parse.
- Flagged when `verdict["logic_error"] is True`.
- No verdict, or a failed call -> not flagged.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Retries |
|---|---|---|---|---|---|---|---|---|
| `plain_llm_mimo` | mimo-v2.6-flash, asked directly | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | not recorded | none |
| `plain_llm_deepseek` | deepseek-v4-flash, asked directly | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | not recorded | none |
| `plain_llm_luna` | gpt-6-luna, asked directly | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | none |
| `plain_llm_grok` | grok-4.1-fast (no reasoning), asked directly | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | none |
| `plain_llm_phi` | Phi-4-mini, asked directly | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | none |

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna)}; not streamed. Our resource URL is hard-coded in bench/llm_client.py and not published here. Caps: Phi-4-mini-instruct 1024, grok-4-1-fast-non-reasoning 8192 output tokens. Phi gets 2 tries of 120 s, other Azure models up to 300 s.

## Prompt text we wrote for the KG tools on this tab

- **uqlm 0.6.8 CodeGenUQ**: 5 fresh solutions are sampled (deepseek-v4-flash-0731, temperature 1.0, max_tokens 8192) from this prompt, then uqlm's own equivalence judge (same model, temperature 0, max_tokens 8192) compares each with the reviewed function:

````text
{spec}

Complete this Python function. Return only the code.
```python
{code lines up to and including the first `def` line}
```
````

  Flagged when `functional_equivalence_rate < 0.5` (run on the first 300 + 300 functions only).
- **pr-agent 0.50.0** `review`: base branch = the function's signature lines plus `    raise NotImplementedError`, change branch = the function, commit message = the task text (first 4,000 characters). Flagged when the review has a `**Possible Issue` section.
