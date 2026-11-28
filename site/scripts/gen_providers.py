"""Write site/src/lib/providers.ts (model makers' logos) from the MIT icon pack @lobehub/icons-static-svg.

  npm pack @lobehub/icons-static-svg && tar xzf lobehub-icons-static-svg-*.tgz
  python site/scripts/gen_providers.py package/icons site/src/lib/providers.ts
"""

import re
import json
import sys
import pathlib

SRC = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
# provider id -> (display name, icon file, regex on the lower-cased model name)
P = [
    ("anthropic", "Anthropic", "anthropic", r"^claude"),
    ("openai", "OpenAI", "openai", r"^(gpt|o\d)"),
    ("deepseek", "DeepSeek", "deepseek", r"^deepseek"),
    ("cohere", "Cohere", "cohere", r"^(command|north)"),
    ("mistral", "Mistral AI", "mistral", r"^(codestral|mistral|devstral|magistral)"),
    ("zai", "Z.ai", "zai", r"^glm"),
    ("xai", "xAI", "xai", r"^grok"),
    ("xiaomi", "Xiaomi", "xiaomimimo", r"^mimo"),
    ("minimax", "MiniMax", "minimax", r"^minimax"),
    ("microsoft", "Microsoft", "microsoft", r"^phi"),
    ("qwen", "Qwen (Alibaba)", "qwen", r"^qwen"),
    ("moonshot", "Moonshot AI", "moonshot", r"^kimi"),
    ("fireworks", "Fireworks AI", "fireworks", r"^ultramarine"),
]
logos = {}
for pid, name, f, rx in P:
    s = (SRC / f"{f}.svg").read_text()
    vb = re.search(r'viewBox="([^"]+)"', s).group(1)
    inner = re.search(r"<svg[^>]*>(.*)</svg>", s, re.S).group(1)
    inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.S).strip()
    assert "<script" not in inner.lower() and "href" not in inner.lower(), f
    logos[pid] = {"name": name, "viewBox": vb, "body": inner, "match": rx}
ts = (
    """// Model makers' logos, shown small before a language model's name (tables, chart tooltips).
// GENERATED from @lobehub/icons-static-svg 1.106.0 (single-colour icons, fill="currentColor"); do not edit by hand.
//
// The icons are from LobeHub's lobe-icons, MIT License, Copyright (c) LobeHub. Permission is hereby granted, free of
// charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish,
// distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to
// do so, subject to the following conditions: The above copyright notice and this permission notice shall be included
// in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
// The logos themselves are the trademarks of their owners and identify whose model a row is; no endorsement implied.

export interface ProviderLogo { name: string; viewBox: string; body: string; match: string }

export const PROVIDER_LOGOS: Record<string, ProviderLogo> = """
    + json.dumps(logos, indent=1)
    + """;

/** Provider id of a language model, from its name (e.g. "claude-opus-5-5" -> "anthropic"); null for tools. */
export function providerOf(model: string): string | null {
  const m = model.toLowerCase();
  for (const [id, p] of Object.entries(PROVIDER_LOGOS)) if (new RegExp(p.match).test(m)) return id;
  return null;
}

/** Inline SVG markup of a model's maker logo (empty string when unknown), 1em square, coloured by the text colour. */
export function logoSvg(model: string, cls = 'plogo'): string {
  const id = providerOf(model);
  if (!id) return '';
  const p = PROVIDER_LOGOS[id];
  return `<svg class="${cls}" viewBox="${p.viewBox}" width="1em" height="1em" fill="currentColor" fill-rule="evenodd" role="img" aria-label="${p.name}"><title>${p.name}</title>${p.body}</svg>`;
}
"""
)
OUT.write_text(ts)
print("wrote", OUT, len(ts), "bytes")
