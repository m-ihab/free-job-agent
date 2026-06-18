"""POST handlers for the CV Studio routes."""
from __future__ import annotations

from job_agent.cv_studio import (
    ats_keyword_radar as _studio_ats_radar,
    auto_fit_one_page as _studio_auto_fit,
    apply_icon_pack as _studio_apply_icon_pack,
    compile_preview as _studio_compile_preview,
    import_github_project as _studio_import_project,
    promote_draft_to_main as _studio_promote_main,
    remove_photo as _studio_remove_photo,
    reorder_sections as _studio_reorder,
    replace_photo as _studio_replace_photo,
    reset_studio_draft as _studio_reset,
    save_studio_draft as _studio_save,
    save_project as _studio_save_project,
    set_studio_language as _studio_set_language,
    single_page_guard as _studio_single_page,
    suggest_edits as _studio_suggest,
    swap_studio_sections as _studio_swap_sections,
    write_asset as _studio_write_asset,
)


def post_asset_save(h, payload) -> None:
    config = h._config()
    name = str(payload.get("name") or "")
    text = str(payload.get("text") or "")
    try:
        h._send_json(_studio_write_asset(config, name, text))
    except ValueError as exc:
        h._send_error_json(str(exc))


def post_replace_photo(h, payload) -> None:
    config = h._config()
    name = str(payload.get("name") or "me.jpg")
    data = str(payload.get("data") or "")
    h._send_json(_studio_replace_photo(config, name, data))


def post_remove_photo(h, payload) -> None:
    h._send_json(_studio_remove_photo(h._config(), str(payload.get("name") or "me.jpg")))


def post_icon_pack(h, payload) -> None:
    h._send_json(_studio_apply_icon_pack(h._config(), str(payload.get("pack") or "moderncv")))


def post_import_github_project(h, payload) -> None:
    h._send_json(_studio_import_project(h._config(), str(payload.get("name") or "")))


def post_project_save(h, payload) -> None:
    config = h._config()
    project = {
        "name": payload.get("name"),
        "url": payload.get("url"),
        "description": payload.get("description"),
        "technologies": payload.get("technologies") if isinstance(payload.get("technologies"), list) else [],
        "bullet_points": payload.get("bullet_points") if isinstance(payload.get("bullet_points"), list) else [],
    }
    h._send_json(_studio_save_project(config, project, promote=bool(payload.get("promote", True))))


def post_single_page_check(h, payload) -> None:
    text = payload.get("text")
    h._send_json(_studio_single_page(h._config(), text if isinstance(text, str) else None))


def post_auto_fit(h, payload) -> None:
    text = str(payload.get("text") or "")
    h._send_json(_studio_auto_fit(h._config(), text))


def post_ats_keywords(h, payload) -> None:
    text = str(payload.get("text") or "")
    role = str(payload.get("role") or "data_scientist")
    h._send_json(_studio_ats_radar(h._config(), text, role))


def post_save(h, payload) -> None:
    text = str(payload.get("text") or "")
    h._send_json(_studio_save(h._config(), text))


def post_reset(h, payload) -> None:
    h._send_json(_studio_reset(h._config()))


def post_promote(h, payload) -> None:
    h._send_json(_studio_promote_main(h._config()))


def post_compile(h, payload) -> None:
    text = payload.get("text")
    h._send_json(_studio_compile_preview(h._config(), text if isinstance(text, str) else None))


def post_reorder(h, payload) -> None:
    text = str(payload.get("text") or "")
    order_raw = payload.get("order") or []
    order = [str(item) for item in order_raw if str(item).strip()]
    rewritten = _studio_reorder(text, order)
    h._send_json({"ok": True, "text": rewritten})


def post_language(h, payload) -> None:
    language = str(payload.get("language") or "").strip().lower()
    h._send_json(_studio_set_language(h._config(), language))


def post_swap_sections(h, payload) -> None:
    label_a = str(payload.get("a") or payload.get("first") or "")
    label_b = str(payload.get("b") or payload.get("second") or "")
    h._send_json(_studio_swap_sections(h._config(), label_a, label_b))


def post_suggest(h, payload) -> None:
    text = str(payload.get("text") or "")
    job_context = str(payload.get("job_context") or "")
    h._send_json(_studio_suggest(text, job_context))
