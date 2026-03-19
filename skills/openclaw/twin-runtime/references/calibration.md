# twin-runtime Calibration Reference

## How calibration works

twin-runtime improves over time through a **calibration flywheel**:

1. **Decision**: Twin recommends an option based on your profile
2. **Outcome**: You record what you actually chose (`twin-runtime reflect`)
3. **Learning**: System updates experience library and detects biases
4. **Improvement**: Future predictions incorporate lessons learned

## Key commands

| Command | Purpose |
|---------|---------|
| `twin-runtime reflect --trace-id <id> --choice "<actual>"` | Record an outcome |
| `twin-runtime heartbeat` | Auto-infer outcomes from git/calendar/email |
| `twin-runtime confirm --list` | View pending implicit reflections |
| `twin-runtime confirm --accept-all` | Accept all pending reflections |
| `twin-runtime evaluate` | Run batch fidelity evaluation |
| `twin-runtime mine-patterns` | Detect systematic failure patterns |

## Metrics

- **Choice Fidelity (CF)**: How often the twin's top prediction matches your actual choice
- **Calibration Quality (CQ)**: How well confidence scores align with actual accuracy
- **Abstention Accuracy**: How well the twin knows what it doesn't know

## Tips

- Record outcomes consistently for best calibration
- Run `heartbeat` daily or via shell hook for passive learning
- Review `mine-patterns` output monthly to catch systematic biases
