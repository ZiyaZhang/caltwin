---
name: twin-calibrate
description: Run batch fidelity evaluation against calibration cases
disable-model-invocation: true
allowed-tools: Bash, Read
---

# Twin Calibrate

Run batch evaluation to measure how well the twin predicts real decisions.

## Process

1. Run:
   ```bash
   twin-runtime evaluate
   ```

2. Present the fidelity report:
   - **CF** (Choice Fidelity) — does twin pick what you'd pick?
   - **RF** (Reasoning Fidelity) — does twin reason like you?
   - **CQ** (Calibration Quality) — does twin know when it's uncertain?
   - **TS** (Temporal Stability) — is twin consistent across runs?
   - Per-domain breakdown
   - MVP gate status (CF >= 0.7)

3. For bias detection, add the flag:
   ```bash
   twin-runtime evaluate --with-bias-detection
   ```
