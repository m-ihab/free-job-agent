"""TDD: GitHub and LinkedIn profile enrichment."""
from __future__ import annotations



from job_agent.profile_enrich import (
    GithubSnapshot,
    merge_github_into_profile,
    parse_linkedin_skills_paste,
    merge_linkedin_skills,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _snapshot(
    handle: str = "octocat",
    languages: dict | None = None,
    repos: list | None = None,
    name: str = "Test User",
) -> GithubSnapshot:
    return GithubSnapshot(
        handle=handle,
        name=name,
        bio="Data scientist",
        location="Paris",
        blog="",
        public_repos=5,
        followers=10,
        languages=languages or {"Python": 50000, "Jupyter Notebook": 20000, "R": 5000},
        repos=repos or [],
    )


def _blank_profile() -> dict:
    return {"contact": {}, "skills": [], "experience": []}


def _blank_master_cv() -> dict:
    return {"contact": {}, "skills": [], "projects": []}


# ── merge_github_into_profile: skills ────────────────────────────────────────

class TestMergeGithubSkills:
    def test_adds_top_languages_as_skills(self) -> None:
        snapshot = _snapshot(languages={"Python": 100000, "SQL": 5000})
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        skill_names = {s["name"].casefold() for s in candidate["skills"]}
        assert "python" in skill_names

    def test_does_not_overwrite_existing_skill(self) -> None:
        snapshot = _snapshot(languages={"Python": 100000})
        candidate = {"contact": {}, "skills": [{"name": "Python", "years_experience": 5}]}
        master_cv = _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        python_entries = [s for s in candidate["skills"] if s["name"].casefold() == "python"]
        assert len(python_entries) == 1, "Should not duplicate existing skill"
        assert python_entries[0]["years_experience"] == 5, "Should not overwrite years_experience"

    def test_report_lists_added_skills(self) -> None:
        snapshot = _snapshot(languages={"Go": 30000, "Rust": 10000})
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        report = merge_github_into_profile(snapshot, candidate, master_cv)
        assert "go" in [s.casefold() for s in report["added_skills"]]

    def test_adds_skills_to_master_cv_too(self) -> None:
        snapshot = _snapshot(languages={"TypeScript": 20000})
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        skill_names = {s["name"].casefold() for s in master_cv["skills"]}
        assert "typescript" in skill_names


# ── merge_github_into_profile: projects ──────────────────────────────────────

class TestMergeGithubProjects:
    def test_adds_repos_as_projects(self) -> None:
        repos = [{"name": "ml-pipeline", "description": "End-to-end ML pipeline", "url": "https://github.com/x/ml-pipeline", "language": "Python", "topics": [], "stars": 3}]
        snapshot = _snapshot(repos=repos)
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        project_names = [p.get("name", "") for p in master_cv["projects"]]
        assert len(project_names) > 0, "At least one project should be added from GitHub repos"
        assert any("ml" in name.lower() or "pipeline" in name.lower() for name in project_names)

    def test_skips_repo_without_description(self) -> None:
        repos = [{"name": "unnamed", "description": "", "url": "https://github.com/x/unnamed", "language": "Python", "topics": [], "stars": 0}]
        snapshot = _snapshot(repos=repos)
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        assert len(master_cv["projects"]) == 0

    def test_does_not_duplicate_existing_project(self) -> None:
        repos = [{"name": "ml-pipeline", "description": "End-to-end ML pipeline", "url": "https://github.com/x/ml-pipeline", "language": "Python", "topics": [], "stars": 3}]
        master_cv = {"contact": {}, "skills": [], "projects": [{"name": "ml-pipeline", "description": "End-to-end ML pipeline"}]}
        candidate = _blank_profile()
        snapshot = _snapshot(repos=repos)
        merge_github_into_profile(snapshot, candidate, master_cv)
        assert len(master_cv["projects"]) == 1, "Should not add duplicate project"

    def test_skips_adding_projects_when_disabled(self) -> None:
        repos = [{"name": "cool-repo", "description": "A cool project", "url": "https://github.com/x/cool-repo", "language": "Python", "topics": [], "stars": 5}]
        snapshot = _snapshot(repos=repos)
        candidate, master_cv = _blank_profile(), _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv, add_projects=False)
        assert len(master_cv["projects"]) == 0


# ── merge_github_into_profile: contact ───────────────────────────────────────

class TestMergeGithubContact:
    def test_sets_github_url_when_missing(self) -> None:
        snapshot = _snapshot(handle="myhandle")
        candidate = {"contact": {}, "skills": []}
        master_cv = _blank_master_cv()
        report = merge_github_into_profile(snapshot, candidate, master_cv)
        assert candidate["contact"]["github_url"] == "https://github.com/myhandle"
        assert report["updated_contact"] is True

    def test_does_not_overwrite_existing_github_url(self) -> None:
        snapshot = _snapshot(handle="newhandle")
        candidate = {"contact": {"github_url": "https://github.com/existing"}, "skills": []}
        master_cv = _blank_master_cv()
        merge_github_into_profile(snapshot, candidate, master_cv)
        assert candidate["contact"]["github_url"] == "https://github.com/existing"


# ── LinkedIn skills paste parser ──────────────────────────────────────────────

class TestLinkedInSkillsPaste:
    def test_parses_bullet_separated_skills(self) -> None:
        text = "Python\n• Machine Learning\n• pandas\n• SQL"
        skills = parse_linkedin_skills_paste(text)
        names = [s.casefold() for s in skills]
        assert "python" in names
        assert "machine learning" in names
        assert "sql" in names

    def test_strips_endorsement_counts(self) -> None:
        text = "Python · 42 endorsements\nDocker · 15 endorsements"
        skills = parse_linkedin_skills_paste(text)
        assert all("endorsement" not in s.lower() for s in skills)
        assert any("python" in s.lower() for s in skills)

    def test_returns_empty_list_for_empty_text(self) -> None:
        skills = parse_linkedin_skills_paste("")
        assert skills == []

    def test_merge_linkedin_skills_adds_new_skills(self) -> None:
        candidate = {"skills": [{"name": "Python"}]}
        master_cv = {"skills": []}
        added = merge_linkedin_skills(["Docker", "Kubernetes", "Python"], candidate, master_cv)
        assert "Docker" in added or "docker" in [s.casefold() for s in added]
        assert "Python" not in added  # already exists
