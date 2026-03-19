---
name: caltwin
description: >
  Calibrated judgment twin for work decisions. Provides personalized
  recommendations calibrated to the user's actual decision-making patterns.
license: Apache-2.0
metadata: {"openclaw":{"requires":{"bins":["twin-runtime"],"env":["ANTHROPIC_API_KEY"]},"install":[{"id":"pip","kind":"pip","package":"twin-runtime","bins":["twin-runtime"]}]}}
homepage: https://github.com/ZiyaZhang/twin-runtime
---

# twin-runtime — Calibrated judgment twin

## When to invoke
- User faces a work decision with 2+ options and trade-offs
- User asks "what would I choose", "what should I do"

## Decision flow
1. Extract question and 2-4 options from context
2. Run: `twin-runtime run "<question>" -o "<opt1>" "<opt2>" --json`
3. Present with honest uncertainty
4. If confidence < 0.5: say "I don't have enough data"

## Recording outcomes
`twin-runtime reflect --trace-id <id> --choice "<actual>"`

## Implicit reflection
Run `twin-runtime heartbeat` periodically (e.g., via cron or shell hook)
to automatically infer outcomes from git activity, calendar, and file changes.

## Boundaries
- REFUSE on personal/medical/legal/financial domains
- DEGRADE on unfamiliar sub-domains
- Present as prediction, never prescription
