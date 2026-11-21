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
- Parser: The answer text after the last `</think>` is scanned from the LAST `{` backwards; the first position where `json.JSONDecoder().raw_decode` yields a dict containing the key `fabrication` is the verdict. No regex fallback.
- Flagged when `verdict["fabrication"]` is truthy (Python truthiness, not `is True`). The line/symbol fields are kept but not used for scoring: any flag on a sample counts.
- No JSON verdict -> not flagged. A call that failed (no reply) is left out of that model's rates.

## Models and request settings

| Row key | Published label | Model id as sent | Provider | temperature | Output budget as sent | Reasoning / extra | Streamed | Retries |
|---|---|---|---|---|---|---|---|---|
| `plain_llm` | deepseek-v4-flash, asked directly | `deepseek-v4-flash-0731` | hyperbolic | 0 | max_tokens 4096 | none sent (provider default; these models think before answering) | no | First pass at max_tokens 4096 (566 answers); the 92 answers that ran out of tokens while thinking were re-run at 16384. Run with the script's own requests call (same body as llm_client, before it existed), not streamed. |
| `plain_llm_glm` | glm-5.3, asked directly | `glm-5.3` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 10 answers that hit 16384 were re-run at 32768 (tool plain_llm_glm_32k). Run before llm_client.py existed (same request body), not streamed. |
| `plain_llm_mimo` | mimo-v2.6-flash, asked directly | `mimo-v2.6-flash` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | Run before llm_client.py existed (same request body), not streamed. |
| `plain_llm_minimax` | minimax-m3, asked directly | `minimax-m3` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | Run before llm_client.py existed (same request body), not streamed. |
| `plain_llm_ds41` | deepseek-v4.1-flash, asked directly | `deepseek-v4.1-flash` | hyperbolic | 0 | max_tokens 16384 | none sent (provider default; these models think before answering) | no | 9 failed or cut-off answers re-run at 32768. |
| `plain_llm_luna` | gpt-6-luna, asked directly | `gpt-6-luna` | azure | not sent (service default) | max_completion_tokens 16384 | reasoning model; no reasoning_effort sent and no temperature sent (Azure accepts only its default) | no | 1 failed or cut-off answer re-run at 32768. |
| `plain_llm_grok` | grok-4.1-fast (no reasoning), asked directly | `grok-4-1-fast-non-reasoning` | azure | 0 | max_completion_tokens 8192 | non-reasoning deployment; nothing sent | no | none |
| `plain_llm_phi` | Phi-4-mini, asked directly | `Phi-4-mini-instruct` | azure | 0 | max_completion_tokens 1024 | none | no | 287 failed or cut-off answers re-run at 32768 (sent as 1024: Azure cap). 17 samples got no reply from Azure (timeouts) and are left out of the rates. 18 stored verdicts were parsed with the earlier parser (first '{' to last '}', json.loads); the current parser would flag them. |
| `plain_llm_gptoss` | gpt-oss-20b on one RTX 4090, asked directly | `openai/gpt-oss-20b` | self_hosted_gpu | 0 | max_tokens 16384 | no reasoning parameter sent (vLLM server default) | no | none |
| `plain_llm_qwen` | Qwen3.8-27B (4-bit) on one RTX 4090, thinking off | `qwen3.8-27b` | self_hosted_gpu | 0 | max_tokens = max(2048, min(16384, 32768 - prompt_chars // 3 - 512)) | thinking off: chat_template_kwargs = {"enable_thinking": false} | no | none |

Providers (OpenAI-compatible chat completions; only key env var names are given):

- **hyperbolic**: https://api.hyperbolic.ai/inference/v1; key env `HYPERBOLIC_API_KEY`. POST {api_base}/chat/completions, header 'Authorization: Bearer <key>', body {model, messages, max_tokens, temperature: 0} plus stream: true and stream_options.include_usage after commit c66e8cf (2026-11-20 12:31); the stream is reassembled into one answer. Hyperbolic routes a model id to upstream providers with their own rates; the weights behind an id are not pinned by us.
- **azure**: https://<your-resource>.services.ai.azure.com/openai/v1 (Azure AI Foundry, OpenAI v1 API); key env `AZURE_API_KEY`. POST {api_base}/chat/completions, header 'api-key: <key>', body {model (deployment name), messages, max_completion_tokens = min(max_tokens, cap), temperature: 0 (not sent for gpt-6-luna)}; not streamed. Our resource URL is hard-coded in bench/llm_client.py and not published here. Caps: Phi-4-mini-instruct 1024, grok-4-1-fast-non-reasoning 8192 output tokens. Phi gets 2 tries of 120 s, other Azure models up to 300 s.
- **self_hosted_gpu**: http://127.0.0.1:8000/v1 (default) (env `SAICA_VLLM_BASE`); key env `SAICA_VLLM_KEY`. POST {api_base}/chat/completions, Bearer key, body {model, messages, max_tokens, temperature: 0} (+ chat_template_kwargs.enable_thinking=false for qwen3.8-27b); not streamed. vLLM on one RunPod RTX 4090 (prefix caching, chunked prefill), reached through an SSH tunnel. qwen3.8-27b = 4-bit community build cyankiwi/Qwen3.8-27B-AWQ-INT4, 32,768-token context.
