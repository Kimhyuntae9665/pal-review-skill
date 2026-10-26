# Diagram sources

- [`review-workflow.svg`](../assets/review-workflow.svg) / [PNG](../assets/review-workflow.png): Korean overview for the main README.
- [`review-vs-debate.svg`](../assets/review-vs-debate.svg) / [PNG](../assets/review-vs-debate.png): bounded one-round and two-round comparison.
- [`pal-review.workflow.json`](pal-review.workflow.json): tracked Archify workflow source with code references; [standalone HTML viewer](pal-review.html), in English.

The illustrations summarize `scripts/pal_review.py` (explicit inputs and preflight checks), `scripts/pal_server.py` (actual PAL transport, one inference POST per call, disabled execution tools), and `scripts/review_rounds.py` (independent reports, conditional peer critique, Codex handoff). Codex follow-through is required by `SKILL.md`; the runner does not launch Codex or prove the artifact correct.

Original vectors; no vendor logos, account data, or screenshots. Model family labels describe configured routes and do not promise current availability. PNG exports use 2× resolution and were visually inspected for Korean glyphs, clipping, arrows, and readability.

To regenerate the PNGs, install Playwright and its Chromium browser, then run `node docs/diagrams/render-assets.cjs`. For an existing browser, set `DIAGRAM_BROWSER` to its executable path. The SVG font stack prefers Malgun Gothic, Apple SD Gothic Neo, or Noto Sans KR.

The Archify viewer is pinned to source commit `ed185a0aa0038f20bc2918e48f760622e9a273c3`. Showcase validation, delivery, strict artifact checks, and automated browser checks passed. Light/dark captures at 1440×900 and 2048×1320 were also visually inspected. See [the compact validation record](validation.json). Local receipts and screenshots remain in the ignored `.archify` folder; no local machine paths are published.
