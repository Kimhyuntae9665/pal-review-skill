# Installation, credentials and recovery

Commands below run from the cloned skill repository. Windows is the primary
tested platform. Git and Python 3.11+ are prerequisites; Node is optional for
rebuilding documentation illustrations, not review execution.

## Pinned local runtime

```powershell
python scripts/bootstrap.py --check
python scripts/bootstrap.py
& ./scripts/pal-review.ps1 doctor
```

The stdlib bootstrap downloads the official
[PAL MCP Server](https://github.com/BeehiveInnovations/pal-mcp-server) checkout at
`7afc7c1cc96e23992c8f105f960132c657883bb1` and creates `.runtime/venv`.
MCP SDK is constrained to 1.30.0; transitive constraints are in `runtime-lock.txt`.
PAL is downloaded under `.runtime/pal-mcp-server`, not copied into this public repo.
Bootstrap uses the invoking Python, verifies the pin/origin/tracked cleanliness,
and checks package compatibility. It never connects credentials or calls models.

The read-only `--check` reports prerequisites and existing managed runtime state.
Successful repeated installation checks are idempotent. Unknown, incomplete or
modified `.runtime` contents are preserved and refused: inspect the error, then
rename that directory to a backup before a fresh install. Never fix a source-pin
failure by disabling checks. Preserve needed logs first.

`references/models.json` contains portable paths resolved against its own location.
Runtime config snapshots normalize those paths so moving the review output does
not silently change the chosen PAL runtime. Do not commit a local absolute-path
override or a source checkout containing `.env`.

## Service connections

| Helper name | Official key console | Required condition |
|---|---|---|
| gemini | [Google AI Studio](https://aistudio.google.com/api-keys) | Free project with paid billing disabled |
| groq | [Groq](https://console.groq.com/keys) | Free organization with paid billing disabled |
| openrouter | [OpenRouter](https://openrouter.ai/settings/keys) | Exact configured :free route and current all-zero numeric pricing |

Register/sign in and create the keys yourself using each service's current UI.
This project does not create accounts, accept terms, bypass login/CAPTCHA,
purchase credits, upgrade plans or increase quotas. OpenRouter's two configured
models share a single account/key; a separate Cohere account is not required.

```powershell
& ./scripts/pal-review.ps1 connect gemini
& ./scripts/pal-review.ps1 connect groq
& ./scripts/pal-review.ps1 connect openrouter
& ./scripts/pal-review.ps1 doctor
```

Keys are accepted only in a hidden local prompt. Google/Groq ask for `FREE`
after you check account billing. This is a local attestation, **not** an automated
billing query or a service spending cap. If the account later changes tier,
disconnect/reconnect after checking billing again.

Windows stores user/machine-bound DPAPI PSCredential XML under
`%LOCALAPPDATA%/CodexPalReview/{provider}.credential.xml`. The helper injects keys
into a single execution and restores prior shell variables. Only the selected
service key reaches the child. It does not change registry environment variables.
Existing encrypted credentials cannot be silently overwritten.

`disconnect gemini` (or groq/openrouter) removes only the local encrypted file;
revoke a leaked key at its service as well. Never supply key arguments, paste
keys into chat, commit credential files, or include keys in screenshots/logs.

`setup-free-review.ps1` offers a local Windows password form. The optional
`setup_browser.py --status-file ABSOLUTE_NEW_JSON` offers a temporary loopback-only
password page with nonce/Host/Origin/CSRF checks. It expires within 15 minutes by
default (maximum 30) and should be closed/stopped after setup. It has no key
readback, inference or billing function. Use a new status-file path.

## Environment-variable mode

For a deliberately managed process environment, variables are `GEMINI_API_KEY`,
`GROQ_API_KEY`, and `OPENROUTER_API_KEY`. Google/Groq also require respectively
`PAL_GEMINI_FREE_TIER_CONFIRMED=1` / `PAL_GROQ_FREE_TIER_CONFIRMED=1` after checking
the same unbilled plan condition. Use a local secret manager or hidden prompt;
do not embed secret values in commands or `.env` files.

On Linux, use `.runtime/venv/bin/python scripts/pal_review.py doctor` and
`.runtime/venv/bin/python scripts/review_rounds.py ...`. DPAPI/Windows UI helpers
do not run there. Linux support is experimental; do not assume a Windows key
store transfers across operating systems.

## Synthetic smoke check

```powershell
& ./scripts/test-cloud-review.ps1 -OutputDirectory './.review-runs/smoke-001'
```

This performs up to four real requests using only the bundled synthetic brief
and weighted-price function. Read every status and compare actual findings with
`tests/fixtures/expected-findings.json`; missing auth is not a successful test.
Preserve old evidence and use a fresh directory. Prefer `rounds plan` when you
only need an offline readiness/packet check.

## Status and recovery

| Status/category | Meaning |
|---|---|
| doctor / planned | Local preparation only; no proof of live inference |
| auth_missing / free_tier_unconfirmed | No inference; connect/check the selected service |
| paid_not_authorized | No inference; paid profile was not explicitly authorized |
| catalog_unavailable / model_unavailable | Public route could not be verified; no inference |
| review_received | Identity/completion/schema accepted; advice still needs verification |
| identity_unverified | Missing, different or excluded reported model; incomplete review |
| incomplete_response / unstructured_response | Truncation/filtering/contract failure; not a pass |
| provider_error | Read normalized HTTP/category and the preserved raw PAL envelope |
| timeout / transport_error | Remote execution can be unknown; preserve reservation, no replay |

HTTP 429 may be a request/token window limit, not an invalid key. HTTP 503 may be
service demand, not missing authentication. No hidden retry, paid substitution,
router fallback or repair plugin is added. A separately authorized diagnostic
after a material fix needs a new result path; previous failures stay intact.

Groq Free's output is capped at 768 tokens with at most one short finding and
the declared strict assessment schema. OpenRouter Free requests two findings
with low reasoning, Gemini up to three. OpenRouter routes do not currently list
`response_format` support; JSON is requested in the prompt and checked locally.
The schema/limits improve completion probability, not factual accuracy.

## PAL boundary

The wrapper starts actual PAL over MCP stdio and exposes chat/version/listmodels.
OpenRouter uses its native PAL provider; Google/Groq use its OpenAI-compatible
custom adapter at official cloud URLs. Use of that SDK does not select an OpenAI
model. The private process replaces general chat instructions with the review
contract and disables generated-code persistence/native conversation offers.
Tracked upstream source and global Codex MCP configuration are unchanged.

Each request permits one fixed official-host/path POST, no redirects/tools,
SDK/PAL retries or broker fallback, and at most 600 seconds. This restriction is
not an OS sandbox. PAL can create local logs under its ignored checkout.

See [rounds.md](rounds.md) for multi-model execution and [../SECURITY.md](../SECURITY.md)
for input/privacy requirements. For offline validation:

```powershell
& ./.runtime/venv/Scripts/python.exe -m unittest discover -s tests -v
```

Mocked tests, live access tests and review-quality evaluations are distinct.
Never describe a public model listing or a mocked response as authenticated access.
