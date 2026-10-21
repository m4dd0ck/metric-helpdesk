# MetricHelpDesk: agent rules

Instructions for coding agents working in this repo; a human reader wants `README.md`. Read
`README.md` for how it works, `RUNBOOK.md` for procedures, `TASK.md` for what is open. The
owner's global agent rules apply on top of these.

- Public repo: no personal data, account numbers, keys or third-party names in any file. The
  API key lives only in the environment; a recorded transcript is checked for it before commit.
- Real-time commits only; never backdate or set `GIT_AUTHOR_DATE`. No AI attribution.
- Release steps: `RUNBOOK.md` §Release.
- The model never writes SQL and the warehouse stays read-only: a change that lets either
  through is a design question for the owner, not a convenience.
- The Claude API path has never run live; say so rather than describing it as tested.
