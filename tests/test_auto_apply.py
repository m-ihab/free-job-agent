from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_agent.auto_apply import (
    _AUTO_APPLY_PROFILE_ENV,
    _USE_REAL_CHROME_PROFILE_ENV,
    _build_apply_qa,
    _select_browser_profile,
    AutoApplySession,
    get_candidates_preview,
)
from job_agent.config import AppConfig
from job_agent.schemas.candidate import CandidateProfile, ContactInfo


def _config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    return AppConfig(
        data_dir=data_dir,
        db_path=data_dir / "jobs.db",
        outputs_dir=data_dir / "outputs",
        profiles_dir=data_dir / "profiles",
    )


def _make_profile(name="Alice Martin", email="alice@example.com", phone="+33 6 00 00 00 00",
                  linkedin="https://linkedin.com/in/alice", github="https://github.com/alice") -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(
            name=name,
            email=email,
            phone=phone,
            linkedin_url=linkedin,
            github_url=github,
        ),
        skills=[],
    )


# ── Phase 1: skip flag reset ──────────────────────────────────────────────────


def test_skip_flag_resets_at_each_job(tmp_path):
    """_skip_flag must be False at the start of each candidate so one skip
    does not cascade to all subsequent candidates."""
    session = AutoApplySession(config=_config(tmp_path))
    # Simulate user clicking Skip for the first job
    session._skip_flag = True
    session._confirm_event.set()

    # The session should expose a method to reset per-job flags
    session._reset_per_job_flags()

    assert session._skip_flag is False


# ── Phase 2: LaTeX timeout ────────────────────────────────────────────────────


def test_latex_compile_raises_on_timeout(tmp_path):
    """compile_latex_to_pdf must raise LatexCompileError when pdflatex
    times out instead of hanging the HTTP thread indefinitely."""
    import subprocess
    from job_agent.renderer.latex_render import LatexCompileError, compile_latex_to_pdf

    tex = tmp_path / "cv.tex"
    tex.write_text(r"\documentclass{article}\begin{document}hi\end{document}", encoding="utf-8")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pdflatex", timeout=120)):
        with patch("job_agent.renderer.latex_render.available_latex_compiler", return_value="/usr/bin/pdflatex"):
            with pytest.raises(LatexCompileError, match="timed out"):
                compile_latex_to_pdf(tex, tmp_path / "cv.pdf")


# ── Phase 4: pre-apply candidate preview ────────────────────────────────────


def test_get_candidates_preview_returns_list_of_dicts():
    """get_candidates_preview returns a list of plain dicts with job and packet
    info — safe to serialise as JSON for the UI."""
    mock_candidate = MagicMock()
    mock_candidate.job.id = "job_abc123"
    mock_candidate.job.title = "Data Scientist"
    mock_candidate.job.company = "Acme Corp"
    mock_candidate.job.location = "Paris"
    mock_candidate.job.apply_url = "https://acme.com/apply"
    mock_candidate.packet.id = "pkt_abc123_v1"
    mock_candidate.packet.fit_score = 82.5

    with patch("job_agent.auto_apply.get_ready_candidates", return_value=[mock_candidate]):
        result = get_candidates_preview(min_score=70, limit=10)

    assert isinstance(result, list)
    assert len(result) == 1
    item = result[0]
    assert item["job_id"] == "job_abc123"
    assert item["title"] == "Data Scientist"
    assert item["company"] == "Acme Corp"
    assert item["location"] == "Paris"
    assert item["apply_url"] == "https://acme.com/apply"
    assert item["packet_id"] == "pkt_abc123_v1"
    assert item["fit_score"] == 82.5


def test_auto_apply_session_accepts_job_id_filter(tmp_path):
    """AutoApplySession initialised with job_ids only processes those IDs."""
    session = AutoApplySession(config=_config(tmp_path), job_ids=["job_aaa", "job_bbb"])

    mock_c1 = MagicMock()
    mock_c1.job.id = "job_aaa"
    mock_c2 = MagicMock()
    mock_c2.job.id = "job_bbb"
    mock_c3 = MagicMock()
    mock_c3.job.id = "job_ccc"  # not in filter

    with patch("job_agent.auto_apply.get_ready_candidates", return_value=[mock_c1, mock_c2, mock_c3]):
        candidates = session._load_candidates()

    ids = [c.job.id for c in candidates]
    assert "job_aaa" in ids
    assert "job_bbb" in ids
    assert "job_ccc" not in ids


# ── Phase 6: contact info injected into QA ───────────────────────────────────


def test_build_apply_qa_includes_full_name():
    profile = _make_profile(name="Alice Martin")
    qa = _build_apply_qa(profile, {})
    assert qa.get("first_name") == "Alice"
    assert qa.get("last_name") == "Martin"


def test_build_apply_qa_includes_email():
    profile = _make_profile(email="alice@example.com")
    qa = _build_apply_qa(profile, {})
    assert qa.get("email") == "alice@example.com"


def test_build_apply_qa_includes_phone():
    profile = _make_profile(phone="+33 6 00 00 00 00")
    qa = _build_apply_qa(profile, {})
    assert qa.get("phone") == "+33 6 00 00 00 00"


def test_build_apply_qa_includes_linkedin():
    profile = _make_profile(linkedin="https://linkedin.com/in/alice")
    qa = _build_apply_qa(profile, {})
    assert qa.get("linkedin_url") == "https://linkedin.com/in/alice"


def test_build_apply_qa_job_answers_take_precedence():
    """Job-specific QA answers override the default contact values."""
    profile = _make_profile(email="alice@example.com")
    job_qa = {"email": "alice.work@corp.com", "why_us": "Great mission"}
    qa = _build_apply_qa(profile, job_qa)
    assert qa["email"] == "alice.work@corp.com"  # job-specific wins
    assert qa["why_us"] == "Great mission"


def test_build_apply_qa_single_name_still_works():
    """ContactInfo.name may be a single token — last_name should be empty string."""
    profile = _make_profile(name="Alice")
    qa = _build_apply_qa(profile, {})
    assert qa["first_name"] == "Alice"
    assert qa["last_name"] == ""


# ── Existing browser-profile tests ──────────────────────────────────────────


def test_auto_apply_uses_dedicated_profile_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.delenv(_USE_REAL_CHROME_PROFILE_ENV, raising=False)

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "dedicated Job Agent"
    assert selected.path == tmp_path / ".job_agent" / "browser_profiles" / "auto_apply"
    assert selected.path.exists()


def test_auto_apply_accepts_custom_profile_dir(tmp_path, monkeypatch):
    custom = tmp_path / "custom-browser-profile"
    monkeypatch.setenv(_AUTO_APPLY_PROFILE_ENV, str(custom))
    monkeypatch.delenv(_USE_REAL_CHROME_PROFILE_ENV, raising=False)

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "custom Job Agent"
    assert selected.path == custom
    assert selected.path.exists()


def test_real_chrome_opt_in_falls_back_when_profile_is_locked(tmp_path, monkeypatch):
    real_profile = tmp_path / "Chrome" / "User Data"
    real_profile.mkdir(parents=True)
    (real_profile / "SingletonLock").write_text("locked", encoding="utf-8")
    monkeypatch.setenv(_USE_REAL_CHROME_PROFILE_ENV, "1")
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.setattr("job_agent.auto_apply._find_chrome_profile", lambda: str(real_profile))

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "dedicated Job Agent"
    assert "already in use" in selected.warning
    assert selected.path != real_profile
