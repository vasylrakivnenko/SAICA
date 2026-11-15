---
name: Publishing startup budget
description: Why model and search-index preparation cannot block HTTP startup.
---

Keep heavyweight semantic-search preparation outside the HTTP startup path.
The catalog and health checks must respond without downloading or loading a
sentence-transformer model.

**Why:** An Autoscale publish failed its approximately one-minute readiness
window while preparing retrieval, before the HTTP server opened its port.
Build-time preparation alone did not prevent runtime preparation in that failed
publish, so a warm cache must not be assumed.

**How to apply:** Preserve lazy preparation for Ask requests when changing server
startup. Test the production static homepage and API health response without
calling retrieval or an external model provider. Expect a slower first Ask
request on a cold instance.
