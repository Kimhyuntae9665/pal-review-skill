# Model routing policy

Configuration is the callable allowlist, not a capability or performance promise.
Never use PAL intelligence scores or a random free router to relabel a different
model as the selected reviewer. The default deliberately uses non-OpenAI families
to provide a separate perspective on Codex work; agreement still needs source checks.

| Exact ID | Provider | Free condition |
|---|---|---|
| `gemini-3.8-flash` | Google | Free project, paid billing disabled; actual project limits apply |
| `qwen/qwen3.8-27b` | Groq | Free organization, paid billing disabled; org-specific token/request windows apply |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter | Exact suffix plus live all-zero numeric prices; no personal/confidential input |
| `cohere/north-mini-code:free` | OpenRouter | Exact suffix plus live all-zero numeric prices; shares OpenRouter free quota |

The four routes use three accounts. The OpenRouter Cohere route is not the direct
Cohere trial API, so its direct trial monthly quota does not apply. Likewise,
Qwen's Groq Free route must not be confused with a paid OpenRouter endpoint.
Google Developer API Free quota is separate from a consumer Antigravity pool.

The configured output contract asks Groq for one short finding within 768 tokens,
OpenRouter Free for two, and Gemini for three. This is a practical completion
budget, not a ranking, remaining quota or guaranteed completeness.

`quality` is an optional **paid** single-review profile retained separately.
Its model entries are not advertised as free and require explicit `--allow-paid`.
There is no automatic free→paid or quality→free substitution after inference.
The rounds command uses the free profile only.

All model names/limits and account access may change. A public catalog entry,
connected key, or `doctor` readiness does not establish successful inference or
review accuracy. Use each provider's real console/error response for allowance;
never subtract consumption from a generic advertised plan limit.

Official sources checked 2026-10-26:

- [Google Free Tier pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Google project limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Google compatibility endpoint](https://ai.google.dev/gemini-api/docs/openai)
- [Groq model](https://console.groq.com/docs/model/qwen/qwen3.8-27b)
- [Groq limits](https://console.groq.com/docs/rate-limits)
- [Groq structured output](https://console.groq.com/docs/structured-outputs)
- [OpenRouter current catalog](https://openrouter.ai/api/v1/models)
- [OpenRouter free request limits](https://openrouter.ai/docs/api_reference/limits)
- [Nemotron endpoint and data notice](https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free)
- [Cohere free endpoint](https://openrouter.ai/cohere/north-mini-code:free)

Provider terms/data policies are separate from this wrapper's software license.
