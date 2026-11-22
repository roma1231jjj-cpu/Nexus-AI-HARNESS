"""Запуск демона Nexus-AI-HARNESS."""

import sys

from nexus import update
from nexus.daemon import serve

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--update" in args:
        result = update.apply()
        print(result.get("output") or result.get("reason") or "")
        raise SystemExit(0 if result.get("ok") else 1)
    if "--check-update" in args:
        print(update.check(force=True))
        raise SystemExit(0)
    port = int(next((a for a in args if a.isdigit()), 8848))
    serve(port=port)
