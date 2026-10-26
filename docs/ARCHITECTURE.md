# Architecture and responsibility

![Review packet, bounded model calls and Codex verification](assets/review-workflow.png)

## Three layers

| Layer | Owns | Does not establish |
|---|---|---|
| Codex skill | Goal, permitted excerpts, interpretation, source checks, supported edits and tests | A finding's truth merely because models agree |
| Local wrapper | Config/auth/free gates, bounded packet, source snapshots, MCP launch, identity/schema validation, evidence/usage handoff | OS sandboxing, complete secret detection, billing-state monitoring |
| PAL and cloud provider | Actual MCP ChatTool/provider/SDK route and model response | Independent command execution or web research for this review |

```mermaid
sequenceDiagram
    participant C as Current Codex task
    participant R as review_rounds.py
    participant P as pal_review.py
    participant M as Private PAL MCP process
    participant A as Official model API
    C->>R: Explicit brief, files, free models, new output directory
    R->>R: Snapshot and hash exact source version
    loop Each selected reviewer (up to 4)
        R->>P: Exact model, one request
        P->>P: Input, auth and free-route checks
        P->>M: MCP stdio chat with bounded inline packet
        M->>A: One fixed-model POST; no retry/fallback/tools
        A-->>M: Content, identity, usage or error
        M-->>P: PAL envelope and provenance
        P-->>R: Validated status and preserved evidence
    end
    opt Debate requested and at least 2 successful reviewers
        R->>P: Same source plus bounded own/peer findings
        Note over R,A: At most one additional critique per successful reviewer
    end
    R-->>C: Manifest, usage summary, CODEX_HANDOFF.md
    C->>C: Check evidence; adopt/reject/unresolved; edit and test
```

## Source map

| File | Responsibility |
|---|---|
| `scripts/bootstrap.py` | Pinned public PAL checkout and managed venv; no model inference |
| `scripts/runtime_config.py` | Shared portable configuration/path resolution |
| `scripts/pal-review.ps1` | Windows hidden key prompts, DPAPI storage, process-only credential injection |
| `scripts/pal_review.py` | Single-request packet/gates, reservations, MCP client, parsing/provenance |
| `scripts/pal_server.py` | Private pinned PAL configuration and fixed one-POST transport guard |
| `scripts/review_contract.py` | Compact review-only system/wire schema for each output budget |
| `scripts/review_rounds.py` | Exclusive session, same-source independent/critique rounds, handoff |
| `scripts/review_summary.py` | Local token/status aggregation without inference or quota lookup |

OpenRouter uses PAL's OpenRouter provider. Google and Groq use PAL's custom
OpenAI-compatible adapter pointed only at their official cloud endpoints. The
adapter/SDK name does not imply use of an OpenAI model. Private hooks change PAL's
review prompt and response handling in memory; upstream tracked files remain clean.

The worker models receive the packet without execution tools. Only parsed,
identity-confirmed successful reviews enter peer critique. An unverified model,
malformed JSON, filtered or truncated output cannot become a clean pass.

The CLI does not launch another Codex process or apply source edits. The skill
instructs the current Codex to finish the checked improvement. This keeps a
clear boundary between receiving advice and validating/applying it.

## Evidence and failure

Fresh output directories and per-request reservations prevent accidental replay.
Raw PAL content, hashes and available usage remain local. Ambiguous timeout
markers are preserved. The final report must show partial participation and
missing usage rather than inventing zero consumption or remaining quota.

This diagram describes the wrapper's implemented flow; it is not an architecture
of PAL itself or a guarantee that a particular provider will remain free/available.
