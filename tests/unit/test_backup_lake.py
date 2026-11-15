import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def run(src: Path, dest: Path | None, **env_extra: str):
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT / "src"), **env_extra}
    if dest is not None:
        env["ALGO_LAKE_BACKUP_DIR"] = str(dest)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/backup_lake.py"), "--lake", str(src)],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )


def make(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_the_lake_is_mirrored_verified_and_a_second_run_copies_nothing_new(tmp_path):
    src = make(tmp_path / "lake", {"raw/a/dt=1/v1.bin": b"one", "raw/b/dt=2/v1.bin": b"twotwo"})
    dest = tmp_path / "mirror"
    r = run(src, dest)
    assert (
        r.returncode == 0
        and "2 file(s)" in r.stdout
        and (dest / "raw/b/dt=2/v1.bin").read_bytes() == b"twotwo"
    )
    again = run(src, dest)
    assert again.returncode == 0 and "0 new" in again.stdout


def test_a_file_deleted_from_the_lake_stays_in_the_backup_nothing_is_ever_removed_there(tmp_path):
    src = make(tmp_path / "lake", {"raw/a/v1.bin": b"keep me"})
    dest = tmp_path / "mirror"
    assert run(src, dest).returncode == 0
    (src / "raw/a/v1.bin").unlink()
    assert run(src, dest).returncode == 0
    assert (dest / "raw/a/v1.bin").read_bytes() == b"keep me"


def test_a_changed_file_is_refused_not_silently_overwritten_in_the_backup(tmp_path):
    """The lake is write-once: a source file whose content differs from the backed-up copy is evidence of tampering or corruption."""
    src = make(tmp_path / "lake", {"raw/a/v1.bin": b"original"})
    dest = tmp_path / "mirror"
    assert run(src, dest).returncode == 0
    (src / "raw/a/v1.bin").write_bytes(b"CHANGED!")
    r = run(src, dest)
    assert r.returncode == 1 and "differs from the backup" in r.stdout + r.stderr
    assert (dest / "raw/a/v1.bin").read_bytes() == b"original"


def test_without_a_destination_it_refuses_loudly_and_a_missing_lake_is_an_error(tmp_path):
    src = make(tmp_path / "lake", {"raw/a/v1.bin": b"x"})
    r = run(src, None)
    assert r.returncode == 1 and "ALGO_LAKE_BACKUP_DIR" in r.stdout + r.stderr
    gone = run(tmp_path / "nope", tmp_path / "mirror")
    assert gone.returncode == 1 and "no lake" in gone.stdout + gone.stderr
