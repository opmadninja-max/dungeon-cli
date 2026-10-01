"""Fake LLM that fails N times then succeeds. Uses a counter file."""

import os
import sys
import tempfile

failures = int(os.environ.get("FAKE_FAILURES", "2"))
counter_file = os.environ.get("FAKE_COUNTER_FILE", os.path.join(tempfile.gettempdir(), "fake_llm_counter"))

# Read current count
try:
    with open(counter_file, "r") as f:
        count = int(f.read().strip())
except (FileNotFoundError, ValueError):
    count = 0

# Increment and save
with open(counter_file, "w") as f:
    f.write(str(count + 1))

if count < failures:
    sys.exit(1)
else:
    print('{"ok": true}')
