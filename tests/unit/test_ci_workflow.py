from pathlib import Path

import yaml

CI = Path(__file__).parents[2] / ".github/workflows/ci.yml"


def steps(job: str) -> list[dict]:
    return yaml.safe_load(CI.read_text())["jobs"][job]["steps"]


def test_the_check_job_publishes_the_coverage_report_whether_or_not_the_gate_passed():
    s = steps("check")
    run_check = next(i for i, x in enumerate(s) if x.get("run") == "make check")
    summary = next(x for x in s if "GITHUB_STEP_SUMMARY" in x.get("run", ""))
    upload = next(x for x in s if str(x.get("uses", "")).startswith("actions/upload-artifact"))
    assert s.index(summary) > run_check and s.index(upload) > run_check
    assert summary["if"] == "always()" and upload["if"] == "always()"
    assert "coverage report --format=markdown" in summary["run"]
    assert upload["with"]["path"] == "htmlcov" and upload["with"]["name"] == "coverage-html"


def test_the_pipeline_runs_on_every_push_and_pull_request_and_nightly():
    on = yaml.safe_load(CI.read_text())[True]  # YAML reads the key `on` as the boolean True
    assert "pull_request" in on and "push" in on and on["schedule"][0]["cron"]
