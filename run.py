"""Запуск демона Nexus-AI-HARNESS."""

import sys

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--update" in args or "--check-update" in args:
        # обновление до импорта демона: App() на импорте поднимает конфиг,
        # MCP-процессы и сеть, а «обновить и выйти» этого не требует
        from nexus import update

        if "--update" in args:
            result = update.apply()
            print(result.get("output") or result.get("reason") or "")
            raise SystemExit(0 if result.get("ok") else 1)
        print(update.check(force=True))
        raise SystemExit(0)
    from nexus.daemon import serve

    port = int(next((a for a in args if a.isdigit()), 8848))
    serve(port=port)
