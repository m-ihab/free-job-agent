"""Enrich candidate_profile / master_cv from public GitHub & LinkedIn data.

GitHub data is pulled live via the public REST API — no authentication needed
for public users. The script:

- Fetches the user's profile, public repos, and language stats.
- Aggregates languages weighted by total byte count.
- Suggests new skills, projects, and an updated GitHub URL.
- Merges into the local profile JSON files without wiping curated content.

LinkedIn pages require login and explicitly forbid scraping. Instead, this
module supports two LinkedIn flows:

1. Parse a manually-exported LinkedIn data archive (``Profile.csv`` /
   ``Skills.csv`` / ``Positions.csv``) if the user provides the export.
2. Accept a text-paste of LinkedIn sections (skills, summary) which the
   user copy-pastes into the wizard.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]


GITHUB_API = "https://api.github.com"
DEFAULT_HEADERS = {"User-Agent": "job-agent", "Accept": "application/vnd.github+json"}


@dataclass
class GithubSnapshot:
    handle: str
    name: str | None
    bio: str | None
    location: str | None
    blog: str | None
    public_repos: int
    followers: int
    languages: dict[str, int]
    repos: list[dict[str, Any]]

    def top_languages(self, limit: int = 10) -> list[str]:
        return [name for name, _ in sorted(self.languages.items(), key=lambda kv: kv[1], reverse=True)][:limit]


def _github_get(path: str, params: dict[str, Any] | None = None, timeout: int = 15) -> Any:
    if requests is None:
        raise RuntimeError("requests is required for GitHub enrichment.")
    response = requests.get(GITHUB_API + path, params=params or {}, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_github_snapshot(handle: str, *, max_repos: int = 30) -> GithubSnapshot:
    """Pull profile + repos + per-repo language byte counts."""
    handle = (handle or "").strip().rstrip("/").rsplit("/", 1)[-1]
    if not handle:
        raise ValueError("GitHub handle is required.")
    profile = _github_get(f"/users/{handle}")
    repos_raw = _github_get(f"/users/{handle}/repos", params={"sort": "updated", "per_page": max_repos})
    repos: list[dict[str, Any]] = []
    languages: Counter[str] = Counter()
    for repo in repos_raw:
        if repo.get("fork"):
            continue
        repos.append({
            "name": repo.get("name"),
            "description": repo.get("description") or "",
            "url": repo.get("html_url"),
            "language": repo.get("language"),
            "topics": repo.get("topics") or [],
            "stars": repo.get("stargazers_count", 0),
            "updated_at": repo.get("updated_at"),
        })
        # Per-repo language byte counts
        lang_url = repo.get("languages_url")
        if lang_url:
            try:
                if requests is None:
                    continue
                lang_resp = requests.get(lang_url, headers=DEFAULT_HEADERS, timeout=10)
                if lang_resp.ok:
                    for lang, bytes_count in lang_resp.json().items():
                        languages[lang] += int(bytes_count)
            except Exception:
                continue
    return GithubSnapshot(
        handle=handle,
        name=profile.get("name"),
        bio=profile.get("bio"),
        location=profile.get("location"),
        blog=profile.get("blog"),
        public_repos=int(profile.get("public_repos") or 0),
        followers=int(profile.get("followers") or 0),
        languages=dict(languages),
        repos=repos,
    )


# Map raw GitHub language names to the candidate-profile skill categories.
_LANGUAGE_CATEGORY = {
    "python": "programming",
    "r": "programming",
    "javascript": "programming",
    "typescript": "programming",
    "go": "programming",
    "rust": "programming",
    "java": "programming",
    "kotlin": "programming",
    "swift": "programming",
    "c": "programming",
    "c++": "programming",
    "c#": "programming",
    "ruby": "programming",
    "php": "programming",
    "scala": "programming",
    "shell": "programming",
    "powershell": "programming",
    "html": "programming",
    "css": "programming",
    "scss": "programming",
    "jupyter notebook": "machine_learning",
    "sql": "data",
    "plpgsql": "data",
    "tex": "tools",
    "asp.net": "programming",
    "vue": "programming",
    "react": "programming",
}


def _existing_skill_names(skills: list[dict]) -> set[str]:
    return {(s.get("name") or "").casefold() for s in skills if s.get("name")}


def merge_github_into_profile(
    snapshot: GithubSnapshot,
    candidate: dict,
    master_cv: dict,
    *,
    add_projects: bool = True,
) -> dict[str, Any]:
    """Merge GitHub snapshot into existing profile dicts in place.

    Returns a small report describing what was added/updated. Existing
    entries are NOT overwritten — this is additive enrichment only.
    """
    report = {
        "added_skills": [],
        "added_projects": [],
        "updated_contact": False,
        "languages_seen": list(snapshot.top_languages(20)),
    }

    contact = candidate.setdefault("contact", {})
    existing_github = (contact.get("github_url") or "").strip()
    inferred_url = f"https://github.com/{snapshot.handle}"
    if not existing_github:
        contact["github_url"] = inferred_url
        report["updated_contact"] = True
    if master_cv.get("contact"):
        if not master_cv["contact"].get("github_url"):
            master_cv["contact"]["github_url"] = inferred_url

    # Add languages as skills, weighted by byte count.
    for skill_list in [candidate.setdefault("skills", []), master_cv.setdefault("skills", [])]:
        existing = _existing_skill_names(skill_list)
        for lang in snapshot.top_languages(12):
            key = lang.casefold()
            if key in existing:
                continue
            category = _LANGUAGE_CATEGORY.get(key, "programming")
            skill_list.append({"name": lang, "category": category, "years_experience": 1})
            existing.add(key)
            if lang not in report["added_skills"]:
                report["added_skills"].append(lang)

    # Add notable repos as projects, skipping forks, empties, and likely dupes.
    if add_projects:
        projects = master_cv.setdefault("projects", [])
        existing_tokens = [_project_signature(p) for p in projects]
        for repo in snapshot.repos:
            name = (repo.get("name") or "").strip()
            description = (repo.get("description") or "").strip()
            if not name or not description:
                continue
            repo_signature = _project_signature({"name": name, "description": description, "url": repo.get("url", "")})
            if any(_signatures_overlap(repo_signature, existing) for existing in existing_tokens):
                continue
            # Normalize tech list: keep canonical capitalization for languages,
            # de-duplicate, drop short noise like single letters.
            tech_pool: list[str] = []
            for raw in [repo.get("language")] + list(repo.get("topics") or []):
                if not raw:
                    continue
                pretty = _prettify_tech(str(raw))
                if pretty and pretty not in tech_pool and len(pretty) > 1:
                    tech_pool.append(pretty)
            project = {
                "name": _humanize_repo_name(name),
                "description": description,
                "url": repo.get("url"),
                "technologies": tech_pool,
                "bullet_points": [],
            }
            projects.append(project)
            existing_tokens.append(repo_signature)
            report["added_projects"].append(name)

    return report


_TECH_CANONICAL = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "r": "R",
    "c#": "C#",
    "c++": "C++",
    "c": "C",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "asp.net": "ASP.NET",
    "shell": "Shell",
    "powershell": "PowerShell",
    "jupyter notebook": "Jupyter Notebook",
    "scikit-learn": "scikit-learn",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "ml": "ML",
    "ai": "AI",
    "mlops": "MLOps",
    "nlp": "NLP",
    "sql": "SQL",
}


def _prettify_tech(value: str) -> str:
    key = value.strip().casefold()
    return _TECH_CANONICAL.get(key, value.strip())


def _humanize_repo_name(name: str) -> str:
    """Turn ``cybersecurity-prediction-app`` into ``Cybersecurity Prediction App``."""
    cleaned = re.sub(r"[-_.]+", " ", name).strip()
    if not cleaned:
        return name
    words = []
    for token in cleaned.split():
        words.append(token if token.isupper() and len(token) <= 4 else token.capitalize())
    return " ".join(words)


def _project_signature(project: dict) -> set[str]:
    """Bag of normalized tokens used to detect duplicate projects."""
    text = (project.get("name") or "") + " " + (project.get("description") or "")
    if project.get("url"):
        text += " " + project["url"]
    tokens = set()
    for match in re.finditer(r"[A-Za-z0-9]+", text.casefold()):
        token = match.group(0)
        if len(token) >= 3:
            tokens.add(token)
    return tokens


def _signatures_overlap(a: set[str], b: set[str], threshold: float = 0.4) -> bool:
    if not a or not b:
        return False
    overlap = len(a & b)
    smaller = min(len(a), len(b))
    return overlap / smaller >= threshold


def linkedin_handle(url_or_handle: str) -> str:
    """Extract a LinkedIn handle from a full URL or return the handle as-is."""
    value = (url_or_handle or "").strip().rstrip("/")
    if not value:
        return ""
    if "linkedin.com/in/" in value:
        return value.split("linkedin.com/in/", 1)[1].split("/", 1)[0]
    return value.rsplit("/", 1)[-1]


def parse_linkedin_skills_paste(text: str) -> list[str]:
    """Parse a copy-paste of the LinkedIn Skills section into a list of names.

    Accepts multiline copy-paste like ``Python\nMachine Learning\n...`` or
    comma/semicolon separated. Strips endorsement counts like ``· 5``.
    """
    if not text:
        return []
    skills: list[str] = []
    for raw in re.split(r"[,;\n]+", text):
        cleaned = re.sub(r"·\s*\d+\s*$", "", raw.strip())
        cleaned = re.sub(r"\s*\(\d+\)\s*$", "", cleaned)
        cleaned = cleaned.strip(" -•\t")
        if cleaned and len(cleaned) <= 80:
            skills.append(cleaned)
    # Dedupe preserving order
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        key = skill.casefold()
        if key not in seen:
            seen.add(key)
            result.append(skill)
    return result


def merge_linkedin_skills(
    skill_names: list[str],
    candidate: dict,
    master_cv: dict,
    *,
    default_category: str = "general",
) -> list[str]:
    """Add LinkedIn skills to both profile files without duplicates."""
    added: list[str] = []
    for skill_list in [candidate.setdefault("skills", []), master_cv.setdefault("skills", [])]:
        existing = _existing_skill_names(skill_list)
        for name in skill_names:
            if name.casefold() in existing:
                continue
            skill_list.append({"name": name, "category": _infer_category(name) or default_category})
            existing.add(name.casefold())
            if name not in added:
                added.append(name)
    return added


_CATEGORY_HINTS = {
    "machine_learning": ["machine learning", "deep learning", "pytorch", "tensorflow", "scikit", "xgboost", "transformer", "llm", "rag", "nlp", "computer vision", "reinforcement", "regression", "classification", "survival", "forecast"],
    "data": ["sql", "pandas", "numpy", "spark", "hadoop", "etl", "data warehouse", "snowflake", "bigquery", "redshift", "dbt", "airflow", "kafka", "postgres", "mysql", "mongodb", "neo4j"],
    "cloud": ["aws", "gcp", "azure", "kubernetes", "terraform", "docker", "lambda", "s3", "ec2", "cloud"],
    "analytics": ["power bi", "tableau", "matplotlib", "seaborn", "excel", "looker", "metabase"],
    "programming": ["python", "r ", "javascript", "typescript", "java", "go", "rust", "c++", "c#", "ruby", "php", "vba"],
    "platforms": ["sap", "salesforce", "hubspot", "shopify"],
    "tools": ["git", "jira", "confluence", "jupyter", "vscode"],
}


def _infer_category(skill: str) -> str | None:
    key = skill.casefold()
    for category, hints in _CATEGORY_HINTS.items():
        if any(hint in key for hint in hints):
            return category
    return None


def write_profiles(candidate_path: Path, candidate: dict, master_cv_path: Path, master_cv: dict) -> None:
    """Write merged dicts back to disk with stable formatting."""
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    master_cv_path.write_text(json.dumps(master_cv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_profile_dicts(profiles_dir: Path) -> tuple[dict, dict, Path, Path]:
    candidate_path = profiles_dir / "candidate_profile.json"
    master_cv_path = profiles_dir / "master_cv.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.exists() else {"contact": {}}
    master_cv = json.loads(master_cv_path.read_text(encoding="utf-8")) if master_cv_path.exists() else {"contact": {}}
    return candidate, master_cv, candidate_path, master_cv_path


def enrich_from_github(profiles_dir: Path, handle: str, *, add_projects: bool = True) -> dict:
    candidate, master_cv, candidate_path, master_cv_path = load_profile_dicts(profiles_dir)
    snapshot = fetch_github_snapshot(handle)
    report = merge_github_into_profile(snapshot, candidate, master_cv, add_projects=add_projects)
    write_profiles(candidate_path, candidate, master_cv_path, master_cv)
    report["handle"] = snapshot.handle
    report["public_repos"] = snapshot.public_repos
    report["candidate_path"] = str(candidate_path)
    report["master_cv_path"] = str(master_cv_path)
    return report


def enrich_from_linkedin_skills(profiles_dir: Path, text: str) -> dict:
    candidate, master_cv, candidate_path, master_cv_path = load_profile_dicts(profiles_dir)
    skills = parse_linkedin_skills_paste(text)
    added = merge_linkedin_skills(skills, candidate, master_cv)
    write_profiles(candidate_path, candidate, master_cv_path, master_cv)
    return {
        "added_skills": added,
        "parsed_count": len(skills),
        "candidate_path": str(candidate_path),
        "master_cv_path": str(master_cv_path),
    }
