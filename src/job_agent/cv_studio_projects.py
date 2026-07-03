"""CV Studio — GitHub project import and master_cv.json project management.

Public functions (``import_github_project``, ``save_project``) are re-exported
by :mod:`job_agent.cv_studio`. Shared primitives come from
:mod:`job_agent.cv_studio_core`; this module never imports ``cv_studio`` back.
"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import _active_cv_text, _profiles_root, _write_draft


def _latex_escape_text(value: Any) -> str:
    text = str(value or "").strip()
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _project_cvitem(project: dict[str, Any], *, max_bullets: int = 3) -> str:
    name = _latex_escape_text(project.get("name") or "Selected project")
    desc = _latex_escape_text(project.get("description") or "")
    bullets = [_latex_escape_text(item) for item in (project.get("bullet_points") or []) if str(item).strip()]
    tech = [_latex_escape_text(item) for item in (project.get("technologies") or []) if str(item).strip()]
    pieces: list[str] = []
    if desc:
        pieces.append(desc.rstrip(".") + ".")
    pieces.extend(item.rstrip(".") + "." for item in bullets[:max_bullets])
    if tech:
        pieces.append(r"\textit{Stack: " + ", ".join(tech[:8]) + ".}")
    body = " ".join(pieces) or "Relevant data/AI project selected from the local profile."
    return rf"\cvitem{{\textbf{{{name}}}}}{{{body}}}"


def _projone_command(projects: list[dict[str, Any]], *, max_bullets: int = 3) -> str:
    inner = "".join(_project_cvitem(project, max_bullets=max_bullets) for project in projects)
    return rf"\newcommand{{\projone}}{{{inner}}}"


def _project_to_projone_line(project: dict[str, Any]) -> str:
    return _projone_command([project])


def _replace_projone(text: str, line: str) -> tuple[str, int]:
    """Replace every ``\\projone`` definition with ``line`` (or inject one)."""
    # Remove any previous fallback line we may have injected before the
    # document. The real template defines \projone inside language branches.
    text = re.sub(r"(?m)^\\newcommand\{\\projone\}\{.*\}\n?", "", text)
    pattern = re.compile(r"(?m)^(\s*)\\newcommand\{\\projone\}\{.*\}$")
    rewritten, count = pattern.subn(lambda match: match.group(1) + line, text)
    if count == 0:
        marker = r"\begin{document}"
        if marker in text:
            rewritten = text.replace(marker, line + "\n" + marker, 1)
            count = 1
    return rewritten, count


def _sync_project_into_draft(config: AppConfig, project: dict[str, Any]) -> tuple[bool, str, str]:
    text, _, _ = _active_cv_text(config)
    if not text:
        return False, "", "no_cv_source"
    rewritten, count = _replace_projone(text, _project_to_projone_line(project))
    if count == 0:
        return False, text, "projone_not_found"
    _write_draft(config, rewritten)
    return True, rewritten, f"updated_{count}_projone_command"


def set_key_projects(config: AppConfig, count: int) -> dict[str, Any]:
    """Pack the top-N ``master_cv.json`` projects into the draft's ``\\projone``.

    Uses the master_cv ordering (promote a project first to feature it), the
    same packing shape the per-job LaTeX renderer uses. The caller should run
    the one-page check afterwards — more projects means tighter space.
    """
    count = max(1, min(3, int(count or 1)))
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    master_cv_path = root / "master_cv.json"
    if not master_cv_path.exists():
        return {"ok": False, "reason": "no_master_cv"}
    try:
        master = json.loads(master_cv_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"bad_json: {exc}"}
    projects = [p for p in master.get("projects", []) if isinstance(p, dict)]
    if not projects:
        return {"ok": False, "reason": "no_projects"}
    chosen = projects[:count]
    text, _, _ = _active_cv_text(config)
    if not text:
        return {"ok": False, "reason": "no_cv_source"}
    # Tighter bullet budget when stacking several projects into one slot.
    max_bullets = 3 if len(chosen) == 1 else 1
    rewritten, replaced = _replace_projone(text, _projone_command(chosen, max_bullets=max_bullets))
    if replaced == 0:
        return {"ok": False, "reason": "projone_not_found"}
    _write_draft(config, rewritten)
    return {
        "ok": True,
        "count": len(chosen),
        "projects": [p.get("name") for p in chosen],
        "text": rewritten,
        "note": f"packed_{len(chosen)}_projects_into_projone",
    }


def import_github_project(config: AppConfig, project_name: str) -> dict[str, Any]:
    """Inject one of the enriched GitHub projects into the CV's ``\\projone``."""
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    master_cv_path = root / "master_cv.json"
    if not master_cv_path.exists():
        return {"ok": False, "reason": "no_master_cv"}
    try:
        master = json.loads(master_cv_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"bad_json: {exc}"}
    project_lookup = {p.get("name", "").casefold(): p for p in master.get("projects", []) if isinstance(p, dict)}
    project = project_lookup.get((project_name or "").casefold())
    if not project:
        return {"ok": False, "reason": "project_not_found"}
    main_tex = root / "main.tex"
    if not main_tex.exists():
        return {"ok": False, "reason": "no_main_tex"}
    # We don't rewrite main.tex content here — the LaTeX renderer already
    # picks the top 3 ranked projects per job. Instead we ensure the project
    # is at the *top* of master_cv.json so the renderer prefers it.
    others = [p for p in master.get("projects", []) if p is not project]
    master["projects"] = [project] + others
    master_cv_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    synced, text, sync_note = _sync_project_into_draft(config, project)
    return {
        "ok": True,
        "promoted": project.get("name"),
        "text": text if synced else "",
        "draft_updated": synced,
        "note": sync_note,
    }


def save_project(config: AppConfig, project: dict[str, Any], *, promote: bool = True) -> dict[str, Any]:
    """Add or update a project in ``master_cv.json``.

    This is intentionally local-profile only. It lets CV Studio capture work
    that lives in a team repository or external repo where the GitHub API will
    not list the project under the user's own account.
    """
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    master_cv_path = root / "master_cv.json"
    if not master_cv_path.exists():
        return {"ok": False, "reason": "no_master_cv"}
    try:
        master = json.loads(master_cv_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"bad_json: {exc}"}

    name = str(project.get("name") or "").strip()
    if not name:
        return {"ok": False, "reason": "name_required"}
    technologies = project.get("technologies") or []
    bullet_points = project.get("bullet_points") or []
    clean_project = {
        "name": name[:100],
        "description": str(project.get("description") or "").strip()[:500],
        "url": str(project.get("url") or "").strip()[:300],
        "technologies": [str(item).strip()[:60] for item in technologies if str(item).strip()][:16],
        "bullet_points": [str(item).strip()[:240] for item in bullet_points if str(item).strip()][:6],
    }

    projects = [p for p in master.get("projects", []) if isinstance(p, dict)]
    existing_index = next((idx for idx, p in enumerate(projects) if str(p.get("name") or "").casefold() == name.casefold()), None)
    if existing_index is None:
        projects.insert(0 if promote else len(projects), clean_project)
        action = "added"
    else:
        projects[existing_index] = {**projects[existing_index], **clean_project}
        if promote:
            projects.insert(0, projects.pop(existing_index))
        action = "updated"
    master["projects"] = projects
    backup = master_cv_path.with_suffix(".json.bak")
    try:
        shutil.copyfile(master_cv_path, backup)
    except Exception:
        pass
    master_cv_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    synced = False
    text = ""
    sync_note = ""
    if promote:
        synced, text, sync_note = _sync_project_into_draft(config, clean_project)
    return {
        "ok": True,
        "action": action,
        "project": clean_project,
        "text": text if synced else "",
        "draft_updated": synced,
        "note": sync_note,
    }
