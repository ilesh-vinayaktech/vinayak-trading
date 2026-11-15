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
