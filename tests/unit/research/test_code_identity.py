import subprocess

from algo.research.code_identity import file_sha256, git_state


def test_git_state_reads_the_commit_and_whether_the_source_is_dirty():
    calls = []

    def run(args, **kw):
        calls.append(args)
        out = {"rev-parse": "abc123\n", "status": " M src/algo/x.py\n"}[args[1]]
        return subprocess.CompletedProcess(args, 0, stdout=out)

    assert git_state(run=run) == ("abc123", True)
    assert calls[1][-3:] == [
        "--",
        "src",
        "config",
    ]  # only the code and configuration decide, not scratch files

    def clean(args, **kw):
        return subprocess.CompletedProcess(
            args, 0, stdout="abc\n" if args[1] == "rev-parse" else ""
        )

    assert git_state(run=clean) == ("abc", False)


def test_without_git_the_state_is_unknown_and_counts_as_dirty():
    def broken(args, **kw):
        raise FileNotFoundError("git")

    assert git_state(run=broken) == ("unknown", True)

    def failing(args, **kw):
        return subprocess.CompletedProcess(args, 128, stdout="")

    assert git_state(run=failing) == ("unknown", True)


def test_a_file_hash_is_the_sha256_of_its_bytes(tmp_path):
    import hashlib

    p = tmp_path / "s.py"
    p.write_bytes(b"print(1)\n")
    assert file_sha256(p) == hashlib.sha256(b"print(1)\n").hexdigest()
    p.write_bytes(b"print(2)\n")
    assert file_sha256(p) == hashlib.sha256(b"print(2)\n").hexdigest()
