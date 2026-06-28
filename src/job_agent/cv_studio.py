"""CV Studio — live editing helpers (facade).

The Studio tab lets the user load their ``main.tex``, edit a draft directly in
the browser, compile it on demand, and pull AI suggestions. All work stays
local. The user's original ``profiles/main.tex`` is never modified unless they
explicitly click "Save as main.tex".

The implementation is split across sibling modules so this file stays small:
  * :mod:`job_agent.cv_studio_core` — shared file-I/O + promote validation
  * :mod:`job_agent.cv_studio_assets` — asset listing, photo, icon packs
  * :mod:`job_agent.cv_studio_projects` — GitHub project import / save
  * :mod:`job_agent.cv_studio_draft` — load / save / reset / promote
  * :mod:`job_agent.cv_studio_sections` — section extract / language / reorder
  * :mod:`job_agent.cv_studio_suggest` — local-AI edit suggestions
  * :mod:`job_agent.cv_studio_fit` — compile preview / page guard / auto-fit
  * :mod:`job_agent.cv_studio_ats` — ATS keyword radar

Everything is re-exported here so the historical public import paths
(``from job_agent.cv_studio import compile_preview, list_assets, ...``) keep
working unchanged. ``copy_latex_assets`` / ``compile_latex_to_pdf`` are imported
here because :mod:`job_agent.cv_studio_fit` reaches them as ``cv_studio.<name>``
— the single seam the studio tests monkeypatch.
"""
from __future__ import annotations

# Compile seam: cv_studio_fit references these as ``cv_studio.<name>`` so the
# tests' ``monkeypatch.setattr(cv_studio, "compile_latex_to_pdf", ...)`` lands.
from job_agent.renderer.latex_render import (  # noqa: F401  (monkeypatch seam)
    LatexCompileError,
    compile_latex_to_pdf,
    copy_latex_assets,
)
from job_agent.cv_studio_core import (  # noqa: F401  (public re-export seam)
    list_main_versions,
    restore_main_version,
)
from job_agent.cv_studio_assets import (  # noqa: F401  (public re-export seam)
    ICON_PACKS,
    apply_icon_pack,
    list_assets,
    read_asset,
    remove_photo,
    replace_photo,
    write_asset,
)
from job_agent.cv_studio_projects import (  # noqa: F401  (public re-export seam)
    import_github_project,
    save_project,
)
from job_agent.cv_studio_draft import (  # noqa: F401  (public re-export seam)
    load_studio,
    promote_draft_to_main,
    reset_studio_draft,
    save_studio_draft,
)
from job_agent.cv_studio_sections import (  # noqa: F401  (public re-export seam)
    _extract_section_titles,
    reorder_sections,
    section_display_name,
    set_studio_language,
    swap_studio_sections,
)
from job_agent.cv_studio_suggest import suggest_edits  # noqa: F401  (public re-export seam)
from job_agent.cv_studio_fit import (  # noqa: F401  (public re-export seam)
    auto_fit_one_page,
    compile_preview,
    single_page_guard,
)
from job_agent.cv_studio_ats import ats_keyword_radar  # noqa: F401  (public re-export seam)
from job_agent.cv_studio_defensibility import defensibility_report  # noqa: F401  (public re-export seam)

__all__ = [
    "load_studio",
    "save_studio_draft",
    "reset_studio_draft",
    "promote_draft_to_main",
    "list_main_versions",
    "restore_main_version",
    "compile_preview",
    "suggest_edits",
    "reorder_sections",
    "section_display_name",
    "set_studio_language",
    "swap_studio_sections",
    "auto_fit_one_page",
    "ats_keyword_radar",
    "defensibility_report",
    "single_page_guard",
    "list_assets",
    "read_asset",
    "write_asset",
    "replace_photo",
    "remove_photo",
    "apply_icon_pack",
    "ICON_PACKS",
    "import_github_project",
    "save_project",
]
