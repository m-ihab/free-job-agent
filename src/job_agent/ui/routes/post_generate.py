"""POST handlers for generation, outreach, coach, audit and reporting routes."""
from __future__ import annotations

from job_agent.apply_bridge import generate_batch_instructions
from job_agent.coach import build_coach_plan as _coach_plan
from job_agent.generator.followup_email import generate_followup_email
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.linkedin_message import (
    generate_linkedin_connect_request,
    generate_linkedin_recruiter_message,
    generate_linkedin_followup_message,
)
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.headhunter import (
    build_batch_outreach,
    english_first_strategy_report,
)
from job_agent.market_intelligence import build_market_report
from job_agent.profile_audit import audit_profile
from job_agent.skill_extractor import extract_implied_skills, suggest_trend_gaps
from job_agent.validators import load_profile_bundle
from job_agent.ui.route_helpers import _tracker


def post_coach_plan(h, payload) -> None:
    h._send_json(_coach_plan(h._config()))


def post_generate_outreach(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    profile, master_cv, _ = load_profile_bundle(config)
    email_md = generate_outreach_email(job, master_cv, profile)
    h._send_json({
        "email_md": email_md,
        "recruiter_name": job.recruiter_name,
        "recruiter_email": job.recruiter_email,
    })


def post_chrome_session(h, payload) -> None:
    min_score = float(payload.get("min_score") or 65)
    limit = int(payload.get("limit") or 10)
    candidates, out_path = generate_batch_instructions(min_score=min_score, limit=limit)
    h._send_json({
        "path": str(out_path),
        "count": len(candidates),
        "message": f"Chrome apply session written: {len(candidates)} application(s) → {out_path}",
    })


def post_linkedin_message(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    msg_type = str(payload.get("type") or "recruiter")
    if not job_id:
        return h._send_error_json("job_id is required.")
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    profile, master_cv, _ = load_profile_bundle(config)
    if msg_type == "connect":
        msg = generate_linkedin_connect_request(job, master_cv, profile)
    elif msg_type == "followup":
        msg = generate_linkedin_followup_message(job, master_cv, profile)
    else:
        msg = generate_linkedin_recruiter_message(job, master_cv, profile)
    h._send_json({"message": msg, "type": msg_type})


def post_audit_profile(h, payload) -> None:
    config = h._config()
    profile, master_cv, _ = load_profile_bundle(config)
    tracker = _tracker(config)
    tracked_jobs = tracker.list_jobs(limit=None)
    report = audit_profile(profile, master_cv, tracked_jobs)
    h._send_json({
        "score": report.strength_score,
        "grade": report.grade,
        "issues": [{"severity": i.severity, "title": i.title, "detail": i.detail, "fix": i.fix} for i in report.issues],
        "implied_skills": report.implied_skills[:15],
        "keyword_gaps": report.keyword_gaps[:10],
        "trend_gaps": report.trend_gaps[:10],
        "strengths": report.strengths,
        "focus_areas": report.focus_areas,
        "markdown": report.to_markdown(),
    })


def post_suggest_skills(h, payload) -> None:
    config = h._config()
    profile, master_cv, _ = load_profile_bundle(config)
    implied = extract_implied_skills(profile, master_cv)
    trends = suggest_trend_gaps(profile)
    h._send_json({
        "implied": [{"name": s.name, "implied_by": s.implied_by} for s in implied[:15]],
        "trending_gaps": trends[:10],
    })


def post_market_report(h, payload) -> None:
    config = h._config()
    profile, _, _ = load_profile_bundle(config)
    tracker = _tracker(config)
    tracked_jobs = tracker.list_jobs(limit=None)
    report = build_market_report(tracked_jobs, set(profile.all_skill_names()))
    h._send_json({
        "total_jobs": report.total_jobs,
        "top_skills": [{"skill": s, "count": c} for s, c in report.top_skills[:15]],
        "contract_breakdown": report.contract_breakdown,
        "french_pct": round(report.language_requirement_pct),
        "remote_pct": round(report.remote_pct),
        "your_match_rate": round(report.your_match_rate),
        "markdown": report.to_markdown(),
    })


def post_interview_prep(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    profile, master_cv, _ = load_profile_bundle(config)
    prep = generate_interview_prep(job, master_cv, profile)
    h._send_json({"prep_md": prep})


def post_followup_email(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    follow_type = str(payload.get("type") or "week1")
    if not job_id:
        return h._send_error_json("job_id is required.")
    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    profile, master_cv, _ = load_profile_bundle(config)
    email_md = generate_followup_email(job, master_cv, profile, follow_type=follow_type)
    h._send_json({"email_md": email_md, "type": follow_type})


def post_headhunter_batch(h, payload) -> None:
    config = h._config()
    min_score = int(payload.get("min_score") or 65)
    english_first = bool(payload.get("english_first") or False)
    profile, master_cv, _ = load_profile_bundle(config)
    tracker = _tracker(config)
    jobs = tracker.list_jobs(limit=None)
    packs = build_batch_outreach(jobs, master_cv, profile, min_score=min_score, english_first_only=english_first)
    h._send_json({
        "count": len(packs),
        "packs": [
            {
                "job_id": p.job_id,
                "job_title": p.job_title,
                "company": p.company,
                "score": p.score,
                "is_english_first": p.is_english_first,
                "connect_request": p.connect_request,
                "recruiter_message": p.recruiter_message,
                "followup_message": p.followup_message,
                "outreach_email": p.outreach_email,
            }
            for p in packs
        ],
    })


def post_headhunter_strategy(h, payload) -> None:
    config = h._config()
    tracker = _tracker(config)
    jobs = tracker.list_jobs(limit=None)
    report = english_first_strategy_report(jobs)
    h._send_json({"report_md": report})
