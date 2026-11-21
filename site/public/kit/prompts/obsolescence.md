# Obsolescence: the reviewer prompt we benchmarked

Mode `obsolescence` · run 2026-11-20 · source `bench/obsolescence/run_tools.py` (constant `PROMPT`, copied verbatim) · 155 solutions calling a deprecated API vs 155 clean (Wang et al. (ICSE'25) deprecated-API map (65 pairs, 8 libraries) + solutions written by 5 models, deprecated call swapped in).

One chat call per sample: a single `user` message holding the filled-in template, no system message, one run per model.

## Placeholders

| Placeholder | Filled with, in the benchmark |
|---|---|
| `{task}` | The coding request the solution was written for (written by gpt-6-luna, naming neither API; the 4 hand-written LLM-SDK pairs use hand-written requests). |
| `{code}` | The solution code (deprecated call swapped in for positives; untouched for negatives). |

## Prompt (verbatim)

Literal braces in the answer line are shown as the model receives them; in the Python source they are doubled (`{{ }}`) for `str.format`.

````text
You are reviewing Python code written by an AI coding assistant.

Question: does this code call a library API that is DEPRECATED or has been REMOVED in the current release of that
library (a function, class, method or argument whose documentation says to use something else instead)? Assume the
user installs the latest versions of all libraries today. Ignore style issues and correctness otherwise.

Task the assistant was given:
<task>
{task}
</task>

Code:
<code>
{code}
</code>

Answer with one JSON object only:
{"uses_deprecated_api": true or false, "evidence": "<the deprecated API and its replacement, or empty>"}
````

## Expected answer and flag rule

- Expected answer: one JSON object, `{"uses_deprecated_api": true or false, "evidence": "<the deprecated API and its replacement, or empty>"}`.
- Parser: The answer text after the last `</think>` is scanned from the LAST `{` backwards; the first position where `json.JSONDecoder().raw_decode` yields a dict containing the key `uses_deprecated_api` is the verdict. If no such object decodes, a regex `"uses_deprecated_api"\s*:\s*(true|false)` is tried as a partial parse.
- Flagged when `verdict["uses_deprecated_api"] is True`.
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
