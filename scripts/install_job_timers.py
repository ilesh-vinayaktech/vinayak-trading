# ruff: noqa: E501
"""Write the systemd user units for the scheduled jobs and print the commands to enable them (changes nothing else).
usage: install_job_timers.py [--out ~/.config/systemd/user] [--uv ~/.local/bin/uv]"""

import argparse
from pathlib import Path

from algo.jobs.registry import JOBS, render_units

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, default=Path.home() / ".config/systemd/user")
ap.add_argument("--uv", default=str(Path.home() / ".local/bin/uv"))
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
for name, text in render_units(str(Path.cwd()), a.uv).items():
    (a.out / name).write_text(text)
print(f"wrote {len(JOBS) + 1} units to {a.out}. Then:\n  systemctl --user daemon-reload")
for j in JOBS:
    print(f"  systemctl --user enable --now algo-job-{j.name}.timer")
print("  loginctl enable-linger $USER   # so timers run when you are logged out")
