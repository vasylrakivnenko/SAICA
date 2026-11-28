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
- Parser: Read by `bench/common.py:parse_verdict`, the same for every mode: the text after the last `</think>`, then the LAST JSON object in it that has the key `dependency_blindness`. If no such object decodes (an answer cut before it closed), the last `"dependency_blindness": true|false` in the text. An echo of the prompt's own answer line (`true or false`) is not a verdict.
- Flagged when the value of `dependency_blindness` is the JSON boolean `true`.
- An answer with no verdict, a value that is not true / false, or a call that failed is UNREADABLE: it is left out of the rates and counted on the row (results.json `unreadable`). It is never counted as 'not flagged'.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Answers with no verdict | Notes |
|---|---|---|---|---|---|---|---|---|---|
| `zero_shot_mimo` | mimo-v2.6-flash | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | 0 of 100 |  |
| `zero_shot_deepseek` | deepseek-v4-flash | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 32768 | none sent (provider default; these models think before answering) | yes | 0 of 100 |  |
| `zero_shot_luna` | gpt-6-luna | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | 0 of 100 |  |
| `zero_shot_grok` | grok-4.1-fast | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | 0 of 100 |  |
| `zero_shot_phi` | Phi-4-mini | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | 6 of 100 |  |
| `zero_shot_haiku` | claude-haiku-5-5 | `claude-haiku-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 100 |  |
| `zero_shot_sonnet` | claude-sonnet-5-5 | `claude-sonnet-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 100 |  |
| `zero_shot_opus55` | claude-opus-5-5 | `claude-opus-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 100 |  |
| `zero_shot_fable` | claude-fable-5-2 | `claude-fable-5-2` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 100 |  |
| `zero_shot_command_r` | command-r-08-2024 | `command-r-08-2024` | cohere | 0 | max_tokens 4096 | non-reasoning model; nothing sent | no | 0 of 100 |  |
| `zero_shot_north_code_thinking_off` | north-mini-code-1.0 | `north-mini-code-1.0` | cohere | 0 | max_tokens 16384 | thinking off: reasoning_effort = "none" | no | 0 of 100 |  |
| `zero_shot_north_code_thinking_on` | north-mini-code-1.0 | `north-mini-code-1.0` | cohere | 0 | max_tokens 32768 | thinking on (the model's default; nothing sent) | no | 5 of 100 |  |
| `zero_shot_codestral` | codestral-2508 | `codestral-2508` | mistral | 0 | max_tokens 16384 | non-reasoning model; nothing sent | no | 0 of 100 |  |
| `zero_shot_gpt54mini` | gpt-5.4-mini | `gpt-5.4-mini` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning_effort = "medium"; no temperature sent (Azure accepts only its default) | no | 0 of 100 |  |

Failed calls and answers cut by the token budget were run again (bench/retry_failed.py; retry budget 32768 output tokens where the provider allows it). Answers that still have no verdict are counted as unreadable on the row, never as 'not flagged'.

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna and gpt-5.4-mini)} (+ reasoning_effort 'medium' for gpt-5.4-mini); not streamed. Our resource URL is read from the environment (SAICA_AZURE_BASE, AZURE_API_BASE or AZURE_KIMI_ENDPOINT) and is not published here. Output caps (bench/llm_client.py MAX_OUT): Phi-4-mini-instruct 1024, command-r-08-2024 4096, grok-4-1-fast-non-reasoning 8192 output tokens.
- **claude_code**: no API call: one `claude -p --model <id> --tools "" --disallowedTools "mcp__*" --system-prompt <one line> --strict-mcp-config --mcp-config {"mcpServers":{}} --disable-slash-commands --setting-sources "" --no-session-persistence --output-format json` process per sample, started in an empty folder, prompt on stdin (bench/llm_client.py:_chat_claude_code). Claude Code 2.1.330 on a Claude subscription. System prompt: 'Answer the user's message in the format it asks for.'. Claude Code adds its environment note (working folder, platform) to the context. An answer is accepted only when it comes from the asked model alone, in one turn, with no tool attempt. CLAUDE_CODE_MAX_OUTPUT_TOKENS is set to the row's output budget.
- **cohere**: https://api.cohere.ai/compatibility/v1; key env `COHERE_API_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_tokens = min(max_tokens, cap), temperature: 0} (+ reasoning_effort "none" for north-mini-code-1.0 thinking-off); not streamed. Cohere's OpenAI-compatible endpoint. command-r-08-2024 refuses max_tokens above 4096. The north-mini-code-1.0 thinking-on row ran on a free trial key (rate-limited, not charged).
- **mistral**: https://api.mistral.ai/v1; key env `MISTRAL_API_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_tokens, temperature: 0}; not streamed. The run used a free Mistral plan (2 requests a minute, one call every 31 s); the cost is priced at Mistral's public list price.
