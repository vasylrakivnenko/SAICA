# Dependency blindness: the reviewer prompt we benchmarked

Mode `dependency_blindness` · run 2026-11-20 · source `bench/dependency_blindness/run_tools.py` (constant `PROMPT`, copied verbatim) · 50 patches that re-implement something already available vs 50 clean (Hand-built on SWE-rebench-OpenHands-Trajectories (Nebius, CC-BY-4.0): correct agent patches, one call re-implemented by hand).

One chat call per sample: a single `user` message holding the filled-in template, no system message, one run per model.

## Placeholders

| Placeholder | Filled with, in the benchmark |
|---|---|
| `{issue}` | The GitHub issue text, first 15,000 characters. |
| `{context}` | Empty string when no repository file is shown (standard-library and NumPy cases). Otherwise, for each shown file (the module that defines the repository helper; both patches of a pair see the same files), this block, concatenated: `\nRepository file (not changed by the patch): <path>\n<file>\n<first 15,000 characters of the file>\n</file>\n` |
| `{patch}` | The agent's patch (unified diff), not truncated. |

## Prompt (verbatim)

Literal braces in the answer line are shown as the model receives them; in the Python source they are doubled (`{{ }}`) for `str.format`.

````text
You are reviewing an AI coding agent's final patch for a GitHub issue.

Question: does the patch show DEPENDENCY BLINDNESS? That is, does it reimplement by hand something that already exists
and was available to it: a standard-library function, a function of a dependency the project already uses, or a helper
that already exists in the repository (relevant repository files are shown below when they exist)? Writing new logic
that has no existing equivalent is not dependency blindness.

Issue:
<issue>
{issue}
</issue>
{context}
The agent's patch (unified diff):
<patch>
{patch}
</patch>

Answer with one JSON object only:
{"dependency_blindness": true or false, "evidence": "<what was reimplemented and what it should have used, or empty>"}
````

## Expected answer and flag rule

- Expected answer: one JSON object, `{"dependency_blindness": true or false, "evidence": "<what was reimplemented and what it should have used, or empty>"}`.
- Parser: The answer text after the last `</think>` is scanned from the LAST `{` backwards; the first position where `json.JSONDecoder().raw_decode` yields a dict containing the key `dependency_blindness` is the verdict. If no such object decodes, a regex `"dependency_blindness"\s*:\s*(true|false)` is tried as a partial parse.
- Flagged when `verdict["dependency_blindness"] is True`.
- No verdict, or a failed call -> not flagged.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Retries |
|---|---|---|---|---|---|---|---|---|
| `plain_llm_mimo` | mimo-v2.6-flash, asked directly | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | none |
| `plain_llm_deepseek` | deepseek-v4-flash, asked directly | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | none |
| `plain_llm_luna` | gpt-6-luna, asked directly | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | none |
| `plain_llm_grok` | grok-4.1-fast (no reasoning), asked directly | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | none |
| `plain_llm_phi` | Phi-4-mini, asked directly | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | none |

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna)}; not streamed. Our resource URL is hard-coded in bench/llm_client.py and not published here. Caps: Phi-4-mini-instruct 1024, grok-4-1-fast-non-reasoning 8192 output tokens. Phi gets 2 tries of 120 s, other Azure models up to 300 s.
