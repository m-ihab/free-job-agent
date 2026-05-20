"""Local smoke test for the France-focused job agent."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from click.testing import CliRunner

from job_agent.cli.main import app


def run() -> int:
    smoke_home = ROOT / ".smoke_home"
    shutil.rmtree(smoke_home, ignore_errors=True)
    os.environ["HOME"] = str(smoke_home)
    sample_job = ROOT / ".smoke_job.txt"
    sample_job.write_text(
        (
            "Data Scientist Intern - Paris\n"
            "Company: Example AI Labs\n"
            "Location: Paris\n\n"
            "We are looking for a Data Scientist Intern with Python, SQL, pandas, "
            "machine learning, experimentation, and dashboarding skills. "
            "This is a 6 month stage in Paris with hybrid work. "
            "Apply at https://example.com/apply\n"
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    commands = [
        ["init"],
        ["copy-examples"],
        ["validate-profile"],
        [
            "process",
            "file",
            str(sample_job),
            "--title",
            "Data Scientist Intern",
            "--company",
            "Example AI Labs",
            "--url",
            "https://example.com/apply",
        ],
        ["list"],
        ["france-search-urls", "--query", "data science stage", "--location", "Paris"],
    ]
    failures = 0
    for command in commands:
        result = runner.invoke(app, command)
        print("$ job-agent " + " ".join(command))
        print(result.output.strip())
        print()
        if result.exit_code != 0:
            failures += 1
    outputs_dir = smoke_home / ".job_agent" / "outputs"
    print("Outputs directory:", outputs_dir)
    return failures


if __name__ == "__main__":
    raise SystemExit(run())
