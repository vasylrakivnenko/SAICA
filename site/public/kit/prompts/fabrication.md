# Fabrication: the reviewer prompt we benchmarked

Mode `fabrication` · run 2026-11-19 · source `bench/fabrication/run_tools.py` (constant `PLAIN_PROMPT`, copied verbatim) · 348 fabricated completions vs 288 clean (Delulu (microsoft/delulu), Python rows).

One chat call per sample: a single `user` message holding the filled-in template, no system message, one run per model.

## Placeholders

| Placeholder | Filled with, in the benchmark |
|---|---|
| `{diff}` | Unified diff of the one changed file, 15 lines of context: `difflib.unified_diff(original, changed, 'a/<path>', 'b/<path>', n=15)`. Original = Delulu's clean file; changed = the same file with the completion (fake or clean). Closest git equivalent: `git diff -U15 -- <file>`. |

## Prompt (verbatim)

Literal braces in the answer line are shown as the model receives them; in the Python source they are doubled (`{{ }}`) for `str.format`.

````text
You are reviewing a code change written by an AI coding assistant.
Below is a unified diff of one file, with surrounding context. The added lines (+) are the change.

Question: does the ADDED code reference any API, package, module, class, function, method, attribute, parameter, or variable that does NOT exist (in the standard library, in the imported third-party packages at their usual current versions, or in this file)?

Answer with JSON only, no prose:
{"fabrication": true|false, "line": <line number in the new file of the offending symbol, or null>, "symbol": "<the non-existent name, or null>", "reason": "<one sentence>"}

Diff:
```diff
{diff}
```
````

## Expected answer and flag rule

- Expected answer: one JSON object, `{"fabrication": true|false, "line": <int or null>, "symbol": "<name or null>", "reason": "<one sentence>"}`.
- Parser: Read by `bench/common.py:parse_verdict`, the same for every mode: the text after the last `</think>`, then the LAST JSON object in it that has the key `fabrication`. If no such object decodes (an answer cut before it closed), the last `"fabrication": true|false` in the text. An echo of the prompt's own answer line (`true or false`) is not a verdict.
- Flagged when the value of `fabrication` is the JSON boolean `true`. The line / symbol fields are kept but not used for scoring: any flag on a sample counts.
- An answer with no verdict, a value that is not true / false, or a call that failed is UNREADABLE: it is left out of the rates and counted on the row (results.json `unreadable`). It is never counted as 'not flagged'.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Answers with no verdict | Notes |
|---|---|---|---|---|---|---|---|---|---|
| `plain_llm` | deepseek-v4-flash, zero-shot | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 4096 | none sent (provider default; these models think before answering) | no | 0 of 636 | First pass at max_tokens 4096; answers that ran out of tokens while thinking were re-run at 16384. Run before bench/llm_client.py existed (same request body), not streamed. |
| `plain_llm_glm` | glm-5.3, zero-shot | `glm-5.3` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 0 of 636 | Answers that hit 16384 were re-run at 32768. Run before bench/llm_client.py existed (same request body), not streamed. |
| `plain_llm_mimo` | mimo-v2.6-flash, zero-shot | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 0 of 636 | Run before bench/llm_client.py existed (same request body), not streamed. |
| `plain_llm_minimax` | minimax-m3, zero-shot | `minimax-m3` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 0 of 636 | Run before bench/llm_client.py existed (same request body), not streamed. |
| `plain_llm_ds41` | deepseek-v4.1-flash, zero-shot | `deepseek-v4.1-flash` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 0 of 636 |  |
| `plain_llm_luna` | gpt-6-luna, zero-shot | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | 0 of 636 |  |
| `plain_llm_grok` | grok-4.1-fast (no reasoning), zero-shot | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | 0 of 636 |  |
| `plain_llm_phi` | Phi-4-mini, zero-shot | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | 26 of 636 |  |
| `plain_llm_gptoss` | gpt-oss-20b on one RTX 4090, zero-shot | `openai/gpt-oss-20b` | self_hosted_gpu | 0 | max_tokens 16384 | no reasoning parameter sent (vLLM server default) | no | 2 of 636 |  |
| `plain_llm_qwen` | Qwen3.8-27B (4-bit) on one RTX 4090, thinking off | `qwen3.8-27b` | self_hosted_gpu | 0 | max_tokens = max(2048, min(16384, 32768 - prompt_chars // 3 - 512)) | thinking off: chat_template_kwargs = {"enable_thinking": false} | no | 0 of 636 |  |
| `plain_llm_haiku` | claude-haiku-5-5 (medium), zero-shot | `claude-haiku-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 636 |  |
| `plain_llm_sonnet` | claude-sonnet-5-5 (medium), zero-shot | `claude-sonnet-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 636 |  |
| `plain_llm_opus55` | claude-opus-5-5 (medium), zero-shot | `claude-opus-5-5` | claude_code | not sent (service default) | CLAUDE_CODE_MAX_OUTPUT_TOKENS 16384 | thinking on, effort medium (Claude Code defaults: no effort level was set, and thinking cannot be switched off for this model) | no | 0 of 636 |  |

Failed calls and answers cut by the token budget were run again (bench/retry_failed.py; retry budget 32768 output tokens where the provider allows it). Answers that still have no verdict are counted as unreadable on the row, never as 'not flagged'.

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna)}; not streamed. Our resource URL is read from the environment (SAICA_AZURE_BASE, AZURE_API_BASE or AZURE_KIMI_ENDPOINT) and is not published here. Output caps (bench/llm_client.py MAX_OUT): Phi-4-mini-instruct 1024, grok-4-1-fast-non-reasoning 8192 output tokens.
- **self_hosted_gpu**: http://127.0.0.1:8000/v1 (default) (env `SAICA_VLLM_BASE`); key env `SAICA_VLLM_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_tokens, temperature: 0} (+ chat_template_kwargs.enable_thinking=false for qwen3.8-27b); not streamed. vLLM on one RunPod RTX 4090 (prefix caching, chunked prefill), reached through an SSH tunnel. qwen3.8-27b = 4-bit community build cyankiwi/Qwen3.8-27B-AWQ-INT4, 32,768-token context.
- **claude_code**: no API call: one `claude -p --model <id> --tools "" --disallowedTools "mcp__*" --system-prompt <one line> --strict-mcp-config --mcp-config {"mcpServers":{}} --disable-slash-commands --setting-sources "" --no-session-persistence --output-format json` process per sample, started in an empty folder, prompt on stdin (bench/llm_client.py:_chat_claude_code). Claude Code 2.1.330 on a Claude subscription. System prompt: 'Answer the user's message in the format it asks for.'. Claude Code adds its environment note (working folder, platform) to the context. An answer is accepted only when it comes from the asked model alone, in one turn, with no tool attempt. CLAUDE_CODE_MAX_OUTPUT_TOKENS is set to the row's output budget.
