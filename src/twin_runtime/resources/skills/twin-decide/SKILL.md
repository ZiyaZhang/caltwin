---
name: twin-decide
description: Run your calibrated judgment twin on a decision scenario
disable-model-invocation: true
argument-hint: "<decision context>"
allowed-tools: Bash, Read
---

# Twin Decide

Help the user run a calibrated judgment twin on a decision scenario.

## Process

1. If the user hasn't provided a clear context + options, ask:
   - "What's the decision situation?"
   - "What are the options to evaluate?"

2. Format and run:
   ```bash
   twin-runtime run "<context>" -o "<option1>" "<option2>" ...
   ```

3. Present the result clearly:
   - **Recommended choice** and full ranking
   - **Key reasoning** from activated domain heads
   - **Uncertainty level** (0-1 scale)
   - **Activated domains** (work, life_planning, money, etc.)

4. If uncertainty > 0.4:
   > "Twin confidence is low here — treat this as a weak signal, not a strong recommendation."

5. Suggest: "Use `/twin-reflect` later to tell the twin what you actually chose — this helps it calibrate."
