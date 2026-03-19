#!/usr/bin/env python3
"""Heartbeat reflection script for OpenClaw shell hook integration.

Usage:
    python heartbeat_reflect.py

This script runs the implicit reflection heartbeat, which:
1. Finds pending decision traces without recorded outcomes
2. Scans git commits, file changes, calendar, and email for signals
3. Auto-reflects high-confidence inferences
4. Queues low-confidence inferences for manual confirmation

Designed to be called from an OpenClaw post-session hook or cron job.
"""

import subprocess
import sys


def main():
    try:
        result = subprocess.run(
            ["twin-runtime", "heartbeat"],
            capture_output=True, text=True, timeout=60,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    except FileNotFoundError:
        print("twin-runtime not found. Install with: pip install twin-runtime", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("Heartbeat timed out after 60s", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
