---
name: Astro runtime compatibility
description: Why the imported website needed an approved upgrade and which runtime assumptions caused setup failures.
---

The user approved upgrading Astro and Node to run the imported website after
both the locked Astro 5 release and its latest patch were blocked by the package
security policy. Preserve the existing Astro structure and Tailwind 3 styling.

**Why:** A safe same-major installation was unavailable; the user explicitly
approved the larger compatibility change rather than stopping setup.

**How to apply:** Do not downgrade to bypass package security. Astro 7 may infer
an agent environment and background the development server automatically;
managed workflows need foreground execution. Bundling can also change
`import.meta.url` locations, so resolve repository-data paths in configuration
before bundling, and check nonempty catalog responses rather than trusting a
successful build alone.
