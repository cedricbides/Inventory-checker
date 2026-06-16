"""
set_password.py — utility script to reset a user's password.

Usage:
    python set_password.py <username> <new_password>

Example:
    python set_password.py admin newpassword123
"""

import hashlib
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "oms.db")


def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def set_password(username: str, password: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            print(f"User '{username}' not found.")
            print("Existing users:")
            for r in conn.execute("SELECT id, username, role FROM users").fetchall():
                print(f"  id={r[0]}  username={r[1]}  role={r[2]}")
            sys.exit(1)

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_pw(password), username),
        )
        conn.commit()
        print(f"Password updated for: {username}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python set_password.py <username> <new_password>")
        sys.exit(1)

    set_password(sys.argv[1], sys.argv[2])