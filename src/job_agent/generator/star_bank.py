"""Grounded STAR story bank for interviews and recruiter screens."""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.generator.evidence_map import extract_job_keywords
from job_agent.schemas.candidate import MasterCV, Project, WorkExperience
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class StarStory:
    title: str
    situation: str
    task: str
    action: str
    result: str
    evidence_refs: list[str]
    matched_keywords: list[str]

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def build_star_bank(job: JobListing, master_cv: MasterCV, *, limit: int = 5) -> list[StarStory]:
    """Build STAR prompts from existing CV experience/projects only.

    Result fields do not invent metrics. If the source bullet has no explicit
    outcome, the story carries a reminder to keep the result qualitative.
    """
    keywords = extract_job_keywords(job)
    stories: list[StarStory] = []
    for index, exp in enumerate(master_cv.experience):
        stories.append(_story_from_experience(exp, keywords, f"master_cv.experience[{index}]"))
    for index, project in enumerate(master_cv.projects):
        stories.append(_story_from_project(project, keywords, f"master_cv.projects[{index}]"))
    stories.sort(key=lambda story: (len(story.matched_keywords), len(story.evidence_refs)), reverse=True)
    return stories[: max(1, limit)]


def render_star_bank_markdown(job: JobListing, master_cv: MasterCV, *, limit: int = 5) -> str:
    stories = build_star_bank(job, master_cv, limit=limit)
    lines = [f"# STAR Story Bank - {job.title} at {job.company}", ""]
    if not stories:
        lines.append("No CV projects or experience were available to build STAR stories.")
        return "\n".join(lines)
    for story in stories:
        lines.extend(
            [
                f"## {story.title}",
                f"- Situation: {story.situation}",
                f"- Task: {story.task}",
                f"- Action: {story.action}",
                f"- Result: {story.result}",
                f"- Matched keywords: {', '.join(story.matched_keywords) or 'No direct keyword overlap'}",
                f"- Evidence refs: {', '.join(story.evidence_refs)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _story_from_experience(exp: WorkExperience, keywords: list[str], ref: str) -> StarStory:
    bullets = list(exp.bullet_points or [])
    techs = list(exp.technologies or [])
    matched = _matched_keywords(keywords, bullets + techs + [exp.title, exp.company])
    title = f"{exp.title} at {exp.company}"
    return StarStory(
        title=title,
        situation=f"{exp.title} role at {exp.company}.",
        task=bullets[0] if bullets else "Use the CV role scope as the task; do not add unverified responsibilities.",
        action=_join_limited(bullets[1:3] + techs[:3], "Describe the concrete tools and steps shown in the CV."),
        result=_result_line(bullets),
        evidence_refs=[ref],
        matched_keywords=matched,
    )


def _story_from_project(project: Project, keywords: list[str], ref: str) -> StarStory:
    bullets = list(project.bullet_points or [])
    techs = list(project.technologies or [])
    matched = _matched_keywords(keywords, [project.name, project.description, *bullets, *techs])
    return StarStory(
        title=project.name,
        situation=project.description or f"Project: {project.name}.",
        task=bullets[0] if bullets else "Explain the project objective exactly as stored in the CV.",
        action=_join_limited(bullets[1:3] + techs[:4], "Describe the implementation using only listed project technologies."),
        result=_result_line(bullets),
        evidence_refs=[ref if not project.url else f"{ref}; {project.url}"],
        matched_keywords=matched,
    )


def _matched_keywords(keywords: list[str], haystack_parts: list[str]) -> list[str]:
    haystack = " ".join(haystack_parts).casefold()
    return [keyword for keyword in keywords if keyword.casefold() in haystack][:8]


def _join_limited(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "; ".join(cleaned[:4]) if cleaned else fallback


def _result_line(bullets: list[str]) -> str:
    for bullet in bullets:
        lower = bullet.casefold()
        if any(signal in lower for signal in ("improved", "reduced", "increased", "delivered", "built", "automated")):
            return bullet
    return "Keep the result qualitative unless you have an exact metric in your local evidence."


__all__ = ["StarStory", "build_star_bank", "render_star_bank_markdown"]
