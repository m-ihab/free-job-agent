"""Route registries for the dashboard HTTP dispatch.

``GET_ROUTES`` and ``POST_ROUTES`` map an exact request path to a handler that
receives the live ``JobAgentHandler`` instance (``h``). POST handlers also
receive the already-parsed JSON ``payload``. Prefix / non-exact GET routes are
handled directly in ``server.do_GET`` (static, ``/api/portfolio/`` assets,
``/file``, the trailing static fallback) since they need ``parsed``/special
matching. This package never imports ``job_agent.ui.server`` — ``server``
imports these registries — which keeps the import graph acyclic.
"""
from __future__ import annotations

from typing import Callable

from job_agent.ui.routes import (
    get_core,
    get_pipeline,
    get_portfolio,
    get_referral,
    post_ai,
    post_autopilot,
    post_cover_letter,
    post_cv_studio,
    post_generate,
    post_portfolio,
    post_preflight,
    post_pipeline,
    post_referral,
    post_search,
)


def _stream_autopilot(h) -> None:
    h._stream_autopilot()


def _stream_auto_apply(h) -> None:
    h._stream_auto_apply()


GET_ROUTES: dict[str, Callable[[object], None]] = {
    "/api/state": get_core.get_state,
    "/api/jobs": get_core.get_jobs,
    "/api/needs-manual": get_core.get_needs_manual,
    "/api/packets": get_core.get_packets,
    "/api/autopilot": get_core.get_autopilot_status,
    "/api/autopilot/stream": _stream_autopilot,
    "/api/auto-apply/stream": _stream_auto_apply,
    "/api/auto-apply/status": get_core.get_auto_apply_status,
    "/api/auto-apply/preview": get_core.get_auto_apply_preview,
    "/api/cv-studio": get_core.get_cv_studio,
    "/api/cv-studio/assets": get_core.get_cv_studio_assets,
    "/api/cv-studio/asset": get_core.get_cv_studio_asset,
    "/api/cv-studio/preview-pdf": get_core.get_cv_studio_preview_pdf,
    "/api/portfolio": get_portfolio.get_portfolio,
    "/api/portfolio/preview": get_portfolio.get_portfolio_preview,
    "/api/portfolio/style.css": get_portfolio.get_portfolio_style_css,
    "/api/ai-status": get_core.get_ai_status,
    "/api/ai-trace": get_core.get_ai_trace,
    "/api/ollama-install": get_core.get_ollama_install,
    "/api/ollama-pull-status": get_core.get_ollama_pull_status,
    "/api/ai-cache": get_core.get_ai_cache,
    "/api/stats": get_core.get_stats,
    "/api/export-csv": get_core.get_export_csv,
    "/api/pipeline/today": get_pipeline.get_pipeline_today,
    "/api/pipeline/stale": get_pipeline.get_pipeline_stale,
    "/api/pipeline/metrics": get_pipeline.get_pipeline_metrics,
    "/api/pipeline/followups": get_pipeline.get_pipeline_followups,
    "/api/pipeline/learning": get_pipeline.get_pipeline_learning,
    "/api/job-notes": get_pipeline.get_job_notes_route,
    "/api/contacts": get_referral.get_contacts,
    "/api/referrals": get_referral.get_referrals,
}


POST_ROUTES: dict[str, Callable[[object, dict], None]] = {
    "/api/search-links": post_search.post_search_links,
    "/api/api-search": post_search.post_api_search,
    "/api/multi-search": post_search.post_multi_search,
    "/api/one-click-hunt": post_search.post_one_click_hunt,
    "/api/add-url": post_search.post_add_url,
    "/api/add-text": post_search.post_add_text,
    "/api/add-bulk": post_search.post_add_bulk,
    "/api/generate-packet": post_search.post_generate_packet,
    "/api/enrich": post_search.post_enrich,
    "/api/enrich-batch": post_search.post_enrich_batch,
    "/api/autopilot/start": post_autopilot.post_autopilot_start,
    "/api/autopilot/stop": post_autopilot.post_autopilot_stop,
    "/api/coach-plan": post_generate.post_coach_plan,
    "/api/portfolio/generate": post_portfolio.post_portfolio_generate,
    "/api/portfolio/save": post_portfolio.post_portfolio_save,
    "/api/portfolio/suggest": post_portfolio.post_portfolio_suggest,
    "/api/portfolio/tagline": post_portfolio.post_portfolio_tagline,
    "/api/portfolio/github-repos": post_portfolio.post_portfolio_github_repos,
    "/api/portfolio/import-github": post_portfolio.post_portfolio_import_github,
    "/api/portfolio/publish-guide": post_portfolio.post_portfolio_publish_guide,
    "/api/preflight": post_preflight.post_preflight,
    "/api/cover-letter": post_cover_letter.post_cover_letter,
    "/api/next-action": post_pipeline.post_next_action,
    "/api/job-notes": post_pipeline.post_job_notes,
    "/api/pipeline/followup-done": post_pipeline.post_followup_done,
    "/api/contacts/import": post_referral.post_contacts_import,
    "/api/referral-ask": post_referral.post_referral_ask,
    "/api/maintenance/rescan-companies": post_autopilot.post_maintenance_rescan_companies,
    "/api/maintenance/dedupe": post_autopilot.post_maintenance_dedupe,
    "/api/maintenance/validate-sources": post_autopilot.post_maintenance_validate_sources,
    "/api/maintenance/clear-broken": post_autopilot.post_maintenance_clear_broken,
    "/api/obsidian-sync": post_autopilot.post_obsidian_sync,
    "/api/cv-studio/asset-save": post_cv_studio.post_asset_save,
    "/api/cv-studio/replace-photo": post_cv_studio.post_replace_photo,
    "/api/cv-studio/remove-photo": post_cv_studio.post_remove_photo,
    "/api/cv-studio/icon-pack": post_cv_studio.post_icon_pack,
    "/api/cv-studio/import-github-project": post_cv_studio.post_import_github_project,
    "/api/cv-studio/project-save": post_cv_studio.post_project_save,
    "/api/cv-studio/single-page-check": post_cv_studio.post_single_page_check,
    "/api/cv-studio/auto-fit": post_cv_studio.post_auto_fit,
    "/api/cv-studio/ats-keywords": post_cv_studio.post_ats_keywords,
    "/api/cv-studio/defensibility": post_cv_studio.post_defensibility,
    "/api/cv-studio/save": post_cv_studio.post_save,
    "/api/cv-studio/reset": post_cv_studio.post_reset,
    "/api/cv-studio/promote": post_cv_studio.post_promote,
    "/api/cv-studio/versions": post_cv_studio.post_versions,
    "/api/cv-studio/restore-version": post_cv_studio.post_restore_version,
    "/api/cv-studio/compile": post_cv_studio.post_compile,
    "/api/cv-studio/reorder": post_cv_studio.post_reorder,
    "/api/cv-studio/language": post_cv_studio.post_language,
    "/api/cv-studio/swap-sections": post_cv_studio.post_swap_sections,
    "/api/cv-studio/suggest": post_cv_studio.post_suggest,
    "/api/ai-chat": post_ai.post_ai_chat,
    "/api/ai-summarize": post_ai.post_ai_summarize,
    "/api/ai-classify": post_ai.post_ai_classify,
    "/api/ollama-launch": post_ai.post_ollama_launch,
    "/api/ollama-pull": post_ai.post_ollama_pull,
    "/api/ai-plan-queries": post_ai.post_ai_plan_queries,
    "/api/ai-analyze": post_ai.post_ai_analyze,
    "/api/enrich-github": post_search.post_enrich_github,
    "/api/enrich-linkedin": post_search.post_enrich_linkedin,
    "/api/export-internships": post_search.post_export_internships,
    "/api/tracker-import": post_search.post_tracker_import,
    "/api/import-cv-template": post_search.post_import_cv_template,
    "/api/status": post_autopilot.post_status,
    "/api/delete-job": post_autopilot.post_delete_job,
    "/api/generate-outreach": post_generate.post_generate_outreach,
    "/api/application-brief": post_generate.post_application_brief,
    "/api/chrome-session": post_generate.post_chrome_session,
    "/api/linkedin-message": post_generate.post_linkedin_message,
    "/api/audit-profile": post_generate.post_audit_profile,
    "/api/suggest-skills": post_generate.post_suggest_skills,
    "/api/market-report": post_generate.post_market_report,
    "/api/interview-prep": post_generate.post_interview_prep,
    "/api/followup-email": post_generate.post_followup_email,
    "/api/headhunter-batch": post_generate.post_headhunter_batch,
    "/api/headhunter-strategy": post_generate.post_headhunter_strategy,
    "/api/auto-apply/start": post_autopilot.post_auto_apply_start,
    "/api/auto-apply/confirm": post_autopilot.post_auto_apply_confirm,
    "/api/auto-apply/skip": post_autopilot.post_auto_apply_skip,
    "/api/auto-apply/cancel": post_autopilot.post_auto_apply_cancel,
    "/api/auto-apply/open-browser": post_autopilot.post_auto_apply_open_browser,
}


# The portfolio asset prefix needs the parsed path, so it is exposed separately
# and dispatched by ``server.do_GET`` after the exact-match lookup misses.
get_portfolio_asset = get_portfolio.get_portfolio_asset
