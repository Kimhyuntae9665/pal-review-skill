# Security and data handling

This is a local client for cloud model review. It is **not an operating-system
sandbox**, a complete secret scanner, or a guarantee that free-tier billing
settings remain unchanged at the provider.

## What leaves your computer

Only the explicit UTF-8 brief and files selected for a review, plus bounded
previous/peer findings when requested, are sent to the configured provider.
PAL adds the review contract. The client does not recursively upload a repository
or give the reviewers shell, browser, filesystem, or other execution tools.

Review packets must resolve inside the supplied working directory. Common secret
filenames and credential patterns are blocked, but this heuristic can miss
secrets. Inspect the exact files before transmission. Never send protected
customer information, credentials, internal documents, or unnecessary personal data.
The NVIDIA free endpoint prohibits personal/confidential data; Google Free Tier
may use submitted material to improve products. Recheck provider policies.

## Credentials

On Windows, `scripts/pal-review.ps1 connect PROVIDER` prompts locally with hidden
input and stores a DPAPI-encrypted PSCredential under the current user's local
application data. Keys are user/machine-bound and never belong in this repository.
The helper injects process variables for one execution and restores them afterward.
Only the selected provider key reaches the PAL child. `disconnect` removes the
local encrypted credential; revoke a leaked key in the provider console as well.

The optional browser setup tool binds only to `127.0.0.1` on a random port, uses
a random URL and CSRF token, validates Host/Origin, refuses cross-origin reads,
does not log keys, and expires after a bounded lifetime. Close it after setup.
It provides no credential readback, overwrite, billing, or inference endpoint.

## Calls and payment

The multi-model command accepts only the configured free profile. OpenRouter
routes must have the exact `:free` suffix and all numeric catalog prices must be
zero before inference. Google/Groq require a local confirmation of the Free plan
with paid billing disabled. This confirmation is **not a billing API check**.
If the service account changes plan, reconnect after verifying its new status.

There are no automatic SDK/PAL retries, broker fallbacks, repair plugins, or
switches to paid models. Each single request allows one inference HTTP POST.
Timeouts may have unknown remote state; preserve the evidence instead of replaying.
The separate paid single-review profile requires explicit per-run authorization.

## Feedback is untrusted

Model output cannot authorize commands, extra uploads, payment, credential access,
or changes outside the user's task. Provider-reported model identity, completion,
and JSON structure are checked. They do not establish factual correctness.
Codex must validate findings against source or meaningful checks before changes.

## Reporting a problem

Use a GitHub issue with a minimal synthetic reproduction and the error category.
Do not attach keys, full private packets, account identifiers, or raw logs without
inspection. For a credential exposure, revoke the key first and describe the
affected mechanism without publishing the credential.
