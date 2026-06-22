"""Form-field detection and QA matching for auto-apply.

Maps visible form fields to candidate answers by label proximity (fuzzy +
heuristic), extracts human-readable field labels from messy ATS DOMs, and builds
the merged QA dict. Re-exported by :mod:`job_agent.auto_apply.driver`.
"""
from __future__ import annotations

from typing import Any


def _fill_visible_fields(page: Any, qa: dict, filled: list[str]) -> None:
    """Match visible form fields to QA answers by label proximity."""
    from rapidfuzz import process as fuzz_process

    qa_keys = list(qa.keys())
    if not qa_keys:
        return

    # Collect all input/textarea/select elements that are visible
    fields = page.locator("input:visible, textarea:visible, select:visible").all()
    for field_el in fields:
        try:
            field_type = field_el.get_attribute("type") or "text"
            if field_type in ("file", "hidden", "submit", "button", "reset", "image"):
                continue

            label_text = _field_label(page, field_el)
            if not label_text:
                continue

            # Fuzzy match the label against QA keys
            match = fuzz_process.extractOne(label_text, qa_keys, score_cutoff=55)
            if not match:
                # Also try matching directly against QA values by common field names
                heuristic = _heuristic_match(label_text, qa)
                if not heuristic:
                    continue
                key, answer = heuristic
            else:
                key = match[0]
                answer = qa[key]

            if not answer:
                continue

            tag = field_el.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                # Try to select matching option
                try:
                    field_el.select_option(label=answer, timeout=1000)
                    filled.append(f"{label_text}: {answer[:60]}")
                except Exception:
                    pass
            elif field_type == "checkbox":
                if str(answer).lower() in ("yes", "true", "1", "oui"):
                    if not field_el.is_checked():
                        field_el.check()
                    filled.append(f"{label_text}: checked")
            else:
                field_el.fill(str(answer))
                filled.append(f"{label_text}: {str(answer)[:60]}")
        except Exception:
            continue


def _field_label(page: Any, field: Any) -> str:
    """Return the human-readable label for a form field.

    Tries multiple strategies in priority order so React/Angular ATS forms
    (which rarely use static <label for="..."> elements) are also handled.
    """
    try:
        # 1. aria-label attribute
        label = field.get_attribute("aria-label") or ""
        if label.strip():
            return label.strip()

        # 2. <label for="id">
        field_id = field.get_attribute("id") or ""
        if field_id:
            label_el = page.locator(f"label[for='{field_id}']").first
            if label_el.count():
                text = label_el.inner_text()
                if text.strip():
                    return text.strip()

        # 3. aria-labelledby — one or more referenced element IDs
        labelledby = field.get_attribute("aria-labelledby") or ""
        if labelledby:
            for ref_id in labelledby.split():
                ref_id = ref_id.strip()
                if not ref_id:
                    continue
                try:
                    ref_el = page.locator(f"#{ref_id}").first
                    if ref_el.count():
                        text = ref_el.inner_text()
                        if text.strip():
                            return text.strip()
                except Exception:
                    pass

        # 4. DOM walk — find the nearest <label> or labelling text node
        try:
            text = field.evaluate("""el => {
                let node = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!node) break;
                    const lbl = node.querySelector(
                        'label, [class*="label" i], [class*="Label"], legend'
                    );
                    if (lbl) {
                        const t = (lbl.innerText || lbl.textContent || '').trim();
                        if (t && t.length < 120) return t;
                    }
                    node = node.parentElement;
                }
                return '';
            }""")
            if text and text.strip():
                return text.strip()
        except Exception:
            pass

        # 5. placeholder
        ph = field.get_attribute("placeholder") or ""
        if ph.strip():
            return ph.strip()

        # 6. autocomplete attribute (e.g. "given-name", "email", "tel")
        ac = field.get_attribute("autocomplete") or ""
        if ac.strip() and ac.lower() not in ("on", "off"):
            return ac.replace("-", " ").replace("_", " ").strip()

        # 7. name attribute as last resort
        name = field.get_attribute("name") or ""
        return name.replace("_", " ").replace("-", " ").strip()
    except Exception:
        return ""


_HEURISTIC_KEYS = {
    "first name": ["first_name", "given_name", "prenom", "prénom", "firstname"],
    "last name": ["last_name", "family_name", "nom", "surname", "lastname"],
    "email": ["email", "e-mail", "courriel", "adresse email"],
    "phone": ["phone", "telephone", "téléphone", "mobile", "portable"],
    "linkedin": ["linkedin_url", "linkedin", "profil linkedin"],
    "github": ["github_url", "github"],
    "city": ["city", "ville", "location"],
    "cover letter": ["cover_letter", "lettre de motivation", "motivation"],
    "why": ["cover_letter", "motivation_text"],
    "salary": ["salary_expectation", "salaire", "pretentions salariales"],
    "work authorization": ["work_authorization", "autorisation travail", "eligible to work"],
    "start date": ["start_date", "availability", "disponibilité", "date de début"],
}


def _build_apply_qa(profile: Any, job_qa: dict) -> dict:
    """Merge candidate contact fields with job-specific QA answers.

    Contact fields (name, email, phone, …) are injected first so the form
    filler can fill even basic fields like "First name" or "Email".
    Job-specific answers take precedence when a key conflicts.
    """
    base: dict[str, str] = {}
    if profile is not None:
        contact = getattr(profile, "contact", None)
        if contact is not None:
            full_name = str(getattr(contact, "name", "") or "").strip()
            parts = full_name.split(None, 1)
            base["first_name"] = parts[0] if parts else ""
            base["last_name"] = parts[1] if len(parts) > 1 else ""
            base["full_name"] = full_name
            base["name"] = full_name
            if getattr(contact, "email", None):
                base["email"] = contact.email
            if getattr(contact, "phone", None):
                base["phone"] = contact.phone
            if getattr(contact, "linkedin_url", None):
                base["linkedin_url"] = contact.linkedin_url
            if getattr(contact, "github_url", None):
                base["github_url"] = contact.github_url
            if getattr(contact, "work_authorization", None):
                base["work_authorization"] = contact.work_authorization
            if getattr(contact, "location", None):
                base["city"] = contact.location
    # Job-specific answers override base contact fields
    return {**base, **{k: v for k, v in (job_qa or {}).items() if v}}


def _heuristic_match(label: str, qa: dict) -> tuple[str, str] | None:
    label_l = label.lower()
    for keyword, candidate_keys in _HEURISTIC_KEYS.items():
        if keyword in label_l:
            for ck in candidate_keys:
                for qa_key, qa_val in qa.items():
                    if ck in qa_key.lower() and qa_val:
                        return qa_key, qa_val
    return None
