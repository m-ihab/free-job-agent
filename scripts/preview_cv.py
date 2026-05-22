"""Print a sample tailored cv.tex so you can eyeball what changes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_agent.renderer.latex_render import render_moderncv_template  # noqa: E402
from job_agent.schemas.candidate import CandidateProfile, MasterCV  # noqa: E402
from job_agent.schemas.job import JobListing  # noqa: E402


def main() -> None:
    profile = CandidateProfile(**json.loads((ROOT / "profiles/candidate_profile.json").read_text(encoding="utf-8")))
    master = MasterCV(**json.loads((ROOT / "profiles/master_cv.json").read_text(encoding="utf-8")))
    job = JobListing(
        title="Data Scientist Intern",
        company="BNP Paribas",
        location="Paris",
        remote=False,
        description="Python, PyTorch, MLOps, NLP, time-series, deep learning.",
        requirements=["Python", "PyTorch", "MLOps", "NLP"],
        tech_stack=["Python", "PyTorch", "MLOps", "NLP", "TensorFlow", "Time-Series"],
    )
    tex = render_moderncv_template(ROOT / "profiles/main.tex", job=job, master_cv=master, profile=profile)
    out_path = ROOT / "preview_cv.tex"
    out_path.write_text(tex, encoding="utf-8")
    print(f"Wrote {out_path} ({len(tex)} chars)")


if __name__ == "__main__":
    main()
