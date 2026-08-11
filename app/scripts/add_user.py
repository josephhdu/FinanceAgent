"""Add a login account. Usage: python scripts/add_user.py <username> <password>

For giving a friend access to your FinanceAI instance.
"""
from __future__ import annotations

import os
import sys

# This script lives in app/scripts/, but the `stock_agent` package lives in
# app/. When you run `python add_user.py`, Python only puts app/scripts/ on the
# import path — so we add the app root (this file's parent's parent) explicitly.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from stock_agent import auth  # noqa: E402  (import after sys.path setup)


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python scripts/add_user.py <username> <password>")
        raise SystemExit(1)
    username, password = sys.argv[1], sys.argv[2]
    auth.init_db()
    if auth.create_user(username, password):
        print(f"Created user '{username}'.")
    else:
        print(f"User '{username}' already exists (or invalid input).")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
