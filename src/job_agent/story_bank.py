"""Persistent STAR(+Reflection) interview story bank.

Stories are seeded verbatim from ``master_cv.json`` (no invented facts — the
S/T/A/R fields contain only text copied from the CV) and can then be edited or
extended manually. Seeding is idempotent: re-syncing never overwrites a story
the user has touched, because sync only inserts ids that do not exist yet.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from job_agent.schemas.candidate import MasterCV
from job_agent.schemas.job import JobListing

_TOKEN_MIN_LENGTH = 3
_SKILL_MATCH_WEIGHT = 3
_TITLE_MATCH_WEIGHT = 2
_TEXT_MATCH_WEIGHT = 1


@dataclass
class Story:
    id: str
    title: str
    skills: list[str] = field(default_factory=list)
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""
    source: str = "manual"

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "skills": self.skills,
            "situation": self.situation,
            "task": self.task,
            "action": self.action,
            "result": self.result,
            "reflection": self.reflection,
            "source": self.source,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Story":
        return cls(
            id=row["id"],
            title=row.get("title", ""),
            skills=list(row.get("skills") or []),
            situation=row.get("situation", ""),
            task=row.get("task", ""),
            action=row.get("action", ""),
            result=row.get("result", ""),
            reflection=row.get("reflection", ""),
            source=row.get("source", "manual"),
        )


def _story_id(source_ref: str) -> str:
    return "story_" + hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:10]


def _bullets_block(bullets: list[str]) -> str:
    return "\n".join(f"- {bullet}" for bullet in bullets if bullet.strip())


def seed_stories_from_cv(master_cv: MasterCV) -> list[Story]:
    """Build grounded stories from experience entries and projects, verbatim."""
    stories: list[Story] = []
    for experience in master_cv.experience:
        ref = f"cv:experience:{experience.company}:{experience.title}"
        stories.append(Story(
            id=_story_id(ref),
            title=f"{experience.title} @ {experience.company}",
            skills=list(experience.technologies),
            situation=f"{experience.title} {experience.company}",
            action=_bullets_block(experience.bullet_points),
            source=ref,
        ))
    for project in master_cv.projects:
        ref = f"cv:project:{project.name}"
        stories.append(Story(
            id=_story_id(ref),
            title=f"Project: {project.name}",
            skills=list(project.technologies),
            situation=project.description,
            action=_bullets_block(project.bullet_points),
            source=ref,
        ))
    return stories


def sync_story_bank(db: Any, master_cv: MasterCV) -> int:
    """Insert missing CV-seeded stories; never touch existing rows. Returns count added."""
    existing_ids = {row["id"] for row in db.list_stories()}
    added = 0
    for story in seed_stories_from_cv(master_cv):
        if story.id not in existing_ids:
            db.save_story(story.to_row())
            added += 1
    return added


def _tokens(text: str) -> set[str]:
    return {token for token in text.lower().replace("/", " ").replace(",", " ").split()
            if len(token) >= _TOKEN_MIN_LENGTH}


def relevant_stories(job: JobListing, stories: list[Story], limit: int = 5) -> list[Story]:
    """Rank stories by overlap with the job's tech stack, requirements, and title."""
    job_tokens = _tokens(" ".join([job.title, *job.tech_stack, *job.requirements]))

    def _score(story: Story) -> int:
        skill_tokens = _tokens(" ".join(story.skills))
        title_tokens = _tokens(story.title)
        text_tokens = _tokens(" ".join([story.situation, story.action, story.result]))
        return (
            len(job_tokens & skill_tokens) * _SKILL_MATCH_WEIGHT
            + len(job_tokens & title_tokens) * _TITLE_MATCH_WEIGHT
            + len(job_tokens & text_tokens) * _TEXT_MATCH_WEIGHT
        )

    ranked = sorted(stories, key=_score, reverse=True)
    return ranked[:max(0, limit)]


def render_story_bank_markdown(job: JobListing, stories: list[Story], missing_requirements: list[str]) -> str:
    """Markdown section: most relevant STAR stories + explicit do-not-claim gaps."""
    lines = ["## Interview story bank", ""]
    if not stories:
        lines.append("_Story bank is empty — run a packet generation once to seed it from your CV, "
                     "or add stories manually._")
    else:
        lines.append(f"Stories most relevant to **{job.title}** at **{job.company}**:")
        for story in stories:
            lines += ["", f"### {story.title}"]
            for label, value in [("Situation", story.situation), ("Task", story.task),
                                 ("Action", story.action), ("Result", story.result),
                                 ("Reflection", story.reflection)]:
                if value.strip():
                    lines.append(f"- **{label}:**" + ("\n" + value if "\n" in value else f" {value}"))
            if story.skills:
                lines.append(f"- **Skills:** {', '.join(story.skills)}")
    if missing_requirements:
        lines += [
            "",
            "### Gaps — do not claim without proof",
            "The job asks for these and your local evidence does not back them. "
            "Prepare an honest answer; **do not claim** them in the interview:",
            *[f"- {gap}" for gap in missing_requirements],
        ]
    return "\n".join(lines) + "\n"
