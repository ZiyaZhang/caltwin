---
name: twin-status
description: Show twin state — domains, reliability, known biases, fidelity summary
disable-model-invocation: true
allowed-tools: Bash, Read
---

# Twin Status

Show the current state of the user's judgment twin.

## Process

1. Run:
   ```bash
   twin-runtime status
   ```

2. Present in a clear summary:
   - **Twin version** and last calibrated date
   - **Available domains** with per-domain reliability scores
   - **Known biases** (if any bias corrections are active)
   - **Fidelity summary** (at minimum CF; later RF/CQ/TS)
   - **Scope declaration** — what the twin can and cannot do

3. If any domain has reliability < 0.5:
   > "This domain needs more calibration data."
