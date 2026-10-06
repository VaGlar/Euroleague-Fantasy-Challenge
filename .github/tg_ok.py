"""Reads Telegram's sendMessage answer (stdin) and fails the step when it was refused.

The workflows used to send with `curl ... > /dev/null`: a refused message (wrong token or chat id,
blocked bot) passed as success and nothing arrived (5/10). Prints only "ok" or Telegram's error
description, never the answer itself: on success it echoes the message and the chat, and the
Actions log is public."""
import json
import sys

try:
    r = json.load(sys.stdin)
except ValueError:
    print("telegram: no JSON answer")
    sys.exit(1)
if r.get("ok"):
    print("telegram: ok")
    sys.exit(0)
print(f"telegram: refused ({r.get('error_code')}): {r.get('description')}")
sys.exit(1)
