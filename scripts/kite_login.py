# ruff: noqa: E501  (usage text and one print line)
"""Daily Kite login. Run once each morning (tokens expire at 6 AM IST; Zerodha does not allow automating the login).

1. Prints the login URL; open it in your browser and sign in to Zerodha (including 2FA).
2. Zerodha redirects to the redirect URL you registered; copy the FULL address from the browser bar (the page may show an
   error: that does not matter) and paste it here, or paste just the request_token.
3. The token is exchanged and saved to data/secrets/kite_token.json (owner-only). It is never printed.
usage: kite_login.py [--request-token TOKEN_OR_URL] [--env .env] [--token-file data/secrets/kite_token.json]"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from algo.data.providers.kite import KiteClient, KiteError, login_url
from algo.data.providers.kite_session import (
    expires_at,
    load_env,
    load_token,
    request_token_from,
    save_token,
    urllib_http,
)

ap = argparse.ArgumentParser()
ap.add_argument("--request-token", default=None)
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
ap.add_argument(
    "--force", action="store_true", help="log in again even if the saved token is still valid"
)
a = ap.parse_args()

env = load_env(a.env)
key, secret = env.get("ZERODHA_API_KEY", ""), env.get("ZERODHA_API_SECRET", "")
if not key or not secret:
    sys.exit("error: ZERODHA_API_KEY and ZERODHA_API_SECRET must be set in the .env file")
now = datetime.now(UTC)
if not a.force and load_token(a.token_file, now) is not None:
    print("already logged in: the saved token is still valid (use --force to log in again)")
    sys.exit(0)
print(f"1. Open this URL, sign in, and approve:\n\n   {login_url(key)}\n")
pasted = a.request_token or input(
    "2. Paste the full address you were redirected to (or just the request_token): "
)
try:
    token = request_token_from(pasted)
    access_token, user_id = KiteClient.exchange_token(key, secret, token, urllib_http)
except (ValueError, KiteError) as e:
    sys.exit(f"login failed: {e}")
issued = datetime.now(UTC)
save_token(a.token_file, access_token, user_id, issued)
print(
    f"logged in as {user_id}; the session is valid until {expires_at(issued).astimezone().strftime('%Y-%m-%d %H:%M %Z')}"
)
