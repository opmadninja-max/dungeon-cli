"""Fake LLM stub for testing the bridge. Reads FAKE_MODE env var."""

import os
import sys
import time

mode = os.environ.get("FAKE_MODE", "happy")

if mode == "happy":
    print('{"ok": true}')
elif mode == "exit1":
    sys.exit(1)
elif mode == "hang":
    time.sleep(60)
elif mode == "empty":
    pass
elif mode == "garbage":
    print("not json {{{")
else:
    print(f"Unknown FAKE_MODE: {mode}", file=sys.stderr)
    sys.exit(1)
