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
- Parser: Read by `bench/common.py:parse_verdict`, the same for every mode: the text after the last `</think>`, then the LAST JSON object in it that has the key `uses_deprecated_api`. If no such object decodes (an answer cut before it closed), the last `"uses_deprecated_api": true|false` in the text. An echo of the prompt's own answer line (`true or false`) is not a verdict.
- Flagged when the value of `uses_deprecated_api` is the JSON boolean `true`.
- An answer with no verdict, a value that is not true / false, or a call that failed is UNREADABLE: it is left out of the rates and counted on the row (results.json `unreadable`). It is never counted as 'not flagged'.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Answers with no verdict | Notes |
|---|---|---|---|---|---|---|---|---|---|
| `zero_shot_mimo` | mimo-v2.6-flash | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | 0 of 310 |  |
| `zero_shot_deepseek` | deepseek-v4-flash | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | 2 of 310 |  |
| `zero_shot_luna` | gpt-6-luna | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | 0 of 310 |  |
| `zero_shot_grok` | grok-4.1-fast | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | 0 of 310 |  |
| `zero_shot_phi` | Phi-4-mini | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | 0 of 310 |  |
| `zero_shot_haiku` | claude-haiku-5-5 | `claude-haiku-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 310 |  |
| `zero_shot_sonnet` | claude-sonnet-5-5 | `claude-sonnet-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 310 |  |
| `zero_shot_opus55` | claude-opus-5-5 | `claude-opus-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 310 |  |
| `zero_shot_fable` | claude-fable-5-2 | `claude-fable-5-2` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 310 |  |
| `zero_shot_command_r` | command-r-08-2024 | `command-r-08-2024` | cohere | 0 | max_tokens 4096 | non-reasoning model; nothing sent | no | 0 of 310 |  |
| `zero_shot_north_code_thinking_off` | north-mini-code-1.0 | `north-mini-code-1.0` | cohere | 0 | max_tokens 16384 | thinking off: reasoning_effort = "none" | no | 1 of 310 |  |
| `zero_shot_gptoss120` | gpt-oss-120b | `openai/gpt-oss-120b` | groq | 0 | max_completion_tokens 16384 | reasoning_effort = "medium" | no | 0 of 310 |  |

Failed calls and answers cut by the token budget were run again (bench/retry_failed.py; retry budget 32768 output tokens where the provider allows it). Answers that still have no verdict are counted as unreadable on the row, never as 'not flagged'.

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna)}; not streamed. Our resource URL is read from the environment (SAICA_AZURE_BASE, AZURE_API_BASE or AZURE_KIMI_ENDPOINT) and is not published here. Output caps (bench/llm_client.py MAX_OUT): Phi-4-mini-instruct 1024, command-r-08-2024 4096, grok-4-1-fast-non-reasoning 8192 output tokens.
- **claude_code**: no API call: one `claude -p --model <id> --tools "" --disallowedTools "mcp__*" --system-prompt <one line> --strict-mcp-config --mcp-config {"mcpServers":{}} --disable-slash-commands --setting-sources "" --no-session-persistence --output-format json` process per sample, started in an empty folder, prompt on stdin (bench/llm_client.py:_chat_claude_code). Claude Code 2.1.330 on a Claude subscription. System prompt: 'Answer the user's message in the format it asks for.'. Claude Code adds its environment note (working folder, platform) to the context. An answer is accepted only when it comes from the asked model alone, in one turn, with no tool attempt. CLAUDE_CODE_MAX_OUTPUT_TOKENS is set to the row's output budget.
- **cohere**: https://api.cohere.ai/compatibility/v1; key env `COHERE_API_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_tokens = min(max_tokens, cap), temperature: 0} (+ reasoning_effort "none" for north-mini-code-1.0 thinking-off); not streamed. Cohere's OpenAI-compatible endpoint. command-r-08-2024 refuses max_tokens above 4096. The north-mini-code-1.0 thinking-on row ran on a free trial key (rate-limited, not charged).
- **groq**: https://api.groq.com/openai/v1; key env `GROQ_API_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_completion_tokens, temperature: 0, reasoning_effort: "medium"}; not streamed. Groq's OpenAI-compatible endpoint. The run used Groq's free plan (8,000 tokens a minute, 200,000 a day); the cost is priced at Groq's public list price.
