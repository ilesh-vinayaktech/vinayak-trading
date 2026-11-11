# ruff: noqa: E501
"""Create the first portal administrator (or another one, from the server's command line).

The password is read from the terminal (never from the command line, so it does not land in shell history or `ps`),
or from PORTAL_ADMIN_PASSWORD for automation. The new admin must enrol a second factor at first sign-in.
usage: portal_create_admin.py --db URL --email you@example.com --name "Your Name" """

import argparse
import getpass
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.portal import accounts
from algo.portal.passwords import Hasher, PasswordPolicyError

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--email", required=True)
ap.add_argument("--name", required=True)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
password = os.environ.get("PORTAL_ADMIN_PASSWORD") or getpass.getpass("Password (12+ characters): ")
if "PORTAL_ADMIN_PASSWORD" not in os.environ and getpass.getpass("Repeat password: ") != password:
    sys.exit("error: the passwords differ")
with psycopg.connect(a.db) as conn:
    migrate(conn)
    try:
        uid = accounts.create_user(
            conn,
            Hasher(),
            email=a.email,
            display_name=a.name,
            role="ADMIN",
            password=password,
            now=datetime.now(UTC),
        )
    except (accounts.AccountError, PasswordPolicyError) as e:
        sys.exit(f"error: {e}")
print(f"created administrator {a.email} ({uid}); they must enrol a second factor at first sign-in")
