# Tasks

Single-repo status, kept by hand. Last reviewed **2026-10-20**.

The latest Claude Code eval run and its score are in `evals/results/claude-code.json`.

## Needs the owner

| Item | Why it is stuck | Added |
|---|---|---|
| **Live-test the Claude API `ask` path** | Needs API credentials the owner does not hold (subscription only). `transcripts/july-dip.json` is a hand-built fixture, the `api` results file under `evals/results/` has never been produced, and the loop depends on a beta header and a `fallbacks` parameter only the fake client has exercised | 2026-10-07 |

## Queue

- [ ] The published transcript's last `query_metrics` call shows a filter as a Python repr
      (`dimension='country' values=['DE']`) in the call log; format filters as text
      (2026-10-07).
