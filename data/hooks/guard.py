"""pre_tool: блокирует разрушительные команды. Код 2 = отказ, stderr уходит модели."""

import json
import sys

payload = json.load(sys.stdin)
tool = payload.get("tool", "")
args = payload.get("args") or {}
command = str(args.get("command", "")).lower()

BLOCK = ("shutdown", "format ", "diskpart", "rm -rf /", "vssadmin delete", "bcdedit")
if tool == "shell" and any(marker in command for marker in BLOCK):
    print(f"нельзя выполнять разрушительную команду: {command[:80]}", file=sys.stderr)
    sys.exit(2)
print("ok")
