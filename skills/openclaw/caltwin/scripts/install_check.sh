#!/bin/bash
# Verify twin-runtime is installed and initialized.

set -e

if ! command -v twin-runtime &> /dev/null; then
    echo "ERROR: twin-runtime not found. Install with: pip install twin-runtime"
    exit 1
fi

if ! twin-runtime status --json &> /dev/null; then
    echo "WARNING: twin not initialized. Run: twin-runtime init"
    exit 1
fi

echo "OK: twin-runtime installed and initialized."
