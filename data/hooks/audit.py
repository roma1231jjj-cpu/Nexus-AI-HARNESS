"""post_tool: пишет журнал вызовов в data/logs/audit.log."""

import json
import sys
import time
from pathlib import Path

payload = json.load(sys.stdin)
log = Path(__file__).resolve().parent.parent / "logs" / "audit.log"
log.parent.mkdir(parents=True, exist_ok=True)
line = (f"[{time.strftime('%F %T')}] {payload.get('session', '')[:8]} "
        f"{payload.get('tool')} ok={payload.get('ok')} {payload.get('ms')}мс "
        f"{str(payload.get('args'))[:120]}\n")
with open(log, "a", encoding="utf-8") as fh:
    fh.write(line)
print("записано")
