"""Local Postgres without Docker: starts an embedded server (pgserver) in .pgdata/ and prints its DATABASE_URL.

    python backend/devdb.py            # prints postgresql+psycopg://...; the server keeps running
    python backend/devdb.py --stop
"""

from __future__ import annotations

import sys
from pathlib import Path

import pgserver

DATA = Path(__file__).resolve().parent.parent / ".pgdata"

if __name__ == "__main__":
    srv = pgserver.get_server(DATA, cleanup_mode=None if "--stop" not in sys.argv else "stop")
    if "--stop" in sys.argv:
        srv.cleanup()
        print("stopped")
    else:
        print(srv.get_uri().replace("postgresql://", "postgresql+psycopg://"))
