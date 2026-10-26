# Validation and reproducibility

The public release is validated separately from the author's previously connected
accounts. No keys, account-specific quotas, private packets, raw live logs or
screenshots of account consoles are published here.

## Public release check — 2026-10-26

| Check | Observed result |
|---|---|
| Clean Windows runtime install | Passed from the official pinned PAL source |
| Managed runtime read-only check | `runtime_ready: true`, no inference |
| Unit / actual-PAL mocked-HTTP suite | 90 tests passed, no skips reported |
| Corrected synthetic example | Seven numerical checks passed |
| Diagram artifact gates | Validate, deliver, strict check and browser-check passed |
| Diagram visual inspection | Two Korean PNGs plus light/dark HTML views inspected |
| Credentials / private account evidence | Excluded from the public tree |

The check used Python 3.11 and PAL 9.8.2 / MCP SDK 1.30.0. Provider keys were not
connected to this clean runtime for release verification. `doctor` correctly
reported missing auth while all local runtime prerequisites were available.
This publication task made no model inference requests.

## Reproduce locally

```powershell
python scripts/bootstrap.py --check
python scripts/bootstrap.py
& ./.runtime/venv/Scripts/python.exe -m unittest discover -s tests -v
& ./.runtime/venv/Scripts/python.exe examples/verify_weighted_price.py
```

The bootstrap check performs read-only local checks. A fresh installation downloads
the public pinned source and packages but does not run inference or connect keys.
The managed runtime refuses unknown/modified or incomplete installations rather
than resetting them. Preserve an interrupted directory under a backup name before
retrying a new installation.

## What the automated tests establish

- Portable default paths resolve against configuration, not the shell cwd;
  frozen session config preserves its selected runtime when output moves.
- Input/file/packet budgets, credential heuristics and output reservations fail
  closed without silently truncating source or replaying a completed request.
- Free/paid selection, provider/key isolation, model identity, output completion,
  wire JSON contracts, retries and fallback restrictions are checked.
- Integration cases use actual PAL MCP, provider and SDK code with mocked HTTP.
- Bounded independent/critique round counts, minimum peer participation and
  untrusted evidence handoff are exercised.
- Returned usage is aggregated independently from unknown remaining allowance;
  missing values are not changed into zero consumption.
- Windows DPAPI tests use synthetic keys in temporary storage, not the author's
  real credential directory; overwrite refusal and round-trip behavior are checked.
- The local browser setup is checked for JavaScript syntax, loopback/Host/Origin/
  CSRF/body restrictions, no secret readback and bounded lifetime.

These checks do **not** establish provider availability for another account,
review accuracy, complete secret detection, visual artifact correctness, or
unlimited free use. An offline success must not be described as live inference.

## Separate live checks

`scripts/test-cloud-review.ps1` is opt-in and sends a real synthetic review request
to each configured model. Use only your own authorized free account, a fresh
output directory and material permitted by the provider. Keep errors/identity/
usage separate from source verification. A successful response proves that
particular request path, not a quality ranking or future availability.

The corrected synthetic example in `examples/` includes seven local numerical
checks. It demonstrates what Codex verification and correction can look like;
it is not an automatic patch generated or applied by the runner.

## Continuous integration

The workflow in [tests.yml](../.github/workflows/tests.yml) configures Windows and
Ubuntu runners, bootstraps the same pinned source, and runs mocked tests without
model keys. Repository permissions are read-only; action revisions are pinned.
Check the actual [Actions run](https://github.com/Kimhyuntae9665/pal-review-skill/actions)
for the commit you use rather than treating the presence of a workflow as a pass.

Documentation SVG/PNG diagrams are source-based explanations, visually inspected
for labels, arrows and clipping. Their rendering/geometry gates are distinct
from executing this review program; see [diagram sources](diagrams/README.md).
