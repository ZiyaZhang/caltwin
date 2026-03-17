---
name: twin-dashboard
description: Generate HTML fidelity dashboard
disable-model-invocation: true
allowed-tools: Bash, Read, Write
---

# Twin Dashboard

Generate a visual fidelity report as an HTML dashboard.

## Process

1. Run:
   ```bash
   twin-runtime dashboard --output fidelity_report.html
   ```

2. Confirm the file was generated, then ask the user:
   > "Dashboard saved. Would you like me to open it in your browser?"

3. If yes:
   ```bash
   twin-runtime dashboard --output fidelity_report.html --open
   ```
