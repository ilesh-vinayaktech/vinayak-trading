from pathlib import Path

from algo.core import secret_scan as s

FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_KEY = "-----BEGIN RSA " + "PRIVATE KEY-----"
FAKE_TOKEN = "ghp_" + "a" * 36


def test_each_kind_of_secret_is_found_with_its_line_number():
    text = f"ok = 1\naws = '{FAKE_AWS}'\n{FAKE_KEY}\ntoken = '{FAKE_TOKEN}'\napi_secret = \"{'x9' * 12}\"\n"
    found = s.scan_text("f.py", text)
    assert [(f.line, f.kind) for f in found] == [
        (2, "aws access key"), (3, "private key"), (4, "github token"), (5, "assigned secret"),
    ]  # fmt: skip
    assert FAKE_AWS not in "".join(f.show() for f in found)  # a finding never repeats the secret


def test_ordinary_code_placeholders_and_allowed_lines_are_not_findings():
    text = (
        'password = os.environ["X"]\napi_key = ""\nsecret = "changeme"\nx = "AKIA..."\ntoken = "'
        + "z" * 30
        + '"  # secret-scan: allow\n'
    )
    assert s.scan_text("f.py", text) == []


def test_a_throwaway_password_in_test_code_is_allowed_but_a_real_key_shape_is_not():
    weak = 'password = "' + "violet-harbor-lantern-42" + '"\n'
    assert s.scan_text("tests/a.py", weak) == [] and len(s.scan_text("src/a.py", weak)) == 1
    assert len(s.scan_text("tests/a.py", f"k = '{FAKE_AWS}'\n")) == 1


def test_a_seeded_secret_in_a_tracked_file_fails_the_repo_scan(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text(f"k = '{FAKE_AWS}'\n")
    assert [f.path for f in s.scan_files(tmp_path, ["a.py", "b.py"])] == ["b.py"]
    assert s.scan_files(tmp_path, ["a.py", "missing.bin"]) == []


def test_the_real_repository_has_no_secret_in_any_tracked_file():
    root = Path(__file__).parents[3]
    assert s.scan_files(root, s.tracked(root)) == []


def test_only_the_exact_test_prefixes_relax_the_weak_rule():
    weak = 'password = "' + "violet-harbor-lantern-42" + '"\n'
    for ok in ("tests/a.py", "frontend/tests/a.tsx"):
        assert s.scan_text(ok, weak) == [], ok
    for bad in ("FRONTEND/TESTS/a.tsx", "frontend/src/a.tsx", "contests/a.py"):
        assert len(s.scan_text(bad, weak)) == 1, bad


def test_an_allowed_line_does_not_hide_the_lines_after_it_and_a_placeholder_is_recognised_in_any_case():
    text = f"k = '{FAKE_AWS}'  # secret-scan: allow\nk2 = '{FAKE_AWS}'\n"
    assert [f.line for f in s.scan_text("a.py", text)] == [2]
    assert (
        s.scan_text("a.py", 'password = "' + "CHANGEME" * 3 + '"\n') == []
    )  # upper-case placeholder text
    assert len(s.scan_text("a.py", 'password = "' + "violet-harbor-lantern-42" + '"\n')) == 1


def test_a_missing_or_binary_file_does_not_stop_the_files_after_it_and_every_finding_is_kept(
    tmp_path: Path,
):
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x80\x81")
    (tmp_path / "one.py").write_text(f"a = '{FAKE_AWS}'\n")
    (tmp_path / "two.py").write_text(f"b = '{FAKE_AWS}'\n")
    got = s.scan_files(tmp_path, ["missing.py", "bin.dat", "one.py", "two.py"])
    assert [f.path for f in got] == ["one.py", "two.py"]


def test_tracked_lists_exactly_the_files_git_knows_in_that_directory_and_refuses_outside_a_repo(
    tmp_path: Path,
):
    import subprocess

    import pytest

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "a.py").write_text("x\n")
    (repo / "sub").mkdir()
    (repo / "sub/b.py").write_text("y\n")
    (repo / "untracked.py").write_text("z\n")
    subprocess.run(["git", "add", "a.py", "sub/b.py"], cwd=repo, check=True)
    assert s.tracked(repo) == ["a.py", "sub/b.py"]
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(subprocess.CalledProcessError):
        s.tracked(plain)
