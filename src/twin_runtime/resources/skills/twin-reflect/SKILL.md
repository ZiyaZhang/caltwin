---
name: twin-reflect
description: Tell your twin what you actually chose — feeds the calibration loop
disable-model-invocation: true
argument-hint: "<what you chose>"
allowed-tools: Bash, Read
---

# Twin Reflect

Record what the user actually decided — this feeds the calibration flywheel.

## Process

1. Ask the user three things:
   - "What did you end up choosing?"
   - "Why?" (optional but valuable)
   - "Where do you think the twin was off — the choice itself, the reasoning, or the confidence level?"

2. If a recent `/twin-decide` was run, try to retrieve the trace_id from that output.

3. Run:
   ```bash
   twin-runtime reflect --choice "<choice>" --reasoning "<why>" \
     --trace-id "<trace_id>" --feedback-target "<choice|reasoning|confidence>"
   ```
   If no trace_id available, omit it (standalone outcome mode).

4. Confirm: "Got it. This will improve the twin's calibration over time."
