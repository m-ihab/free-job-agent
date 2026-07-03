"""Per-ATS-family field-label synonym tables for the auto-apply filler.

Each table maps a lowercase label keyword (as it appears on the form) to QA-key
fragments to look up in the merged QA dict. Family tables extend — never
replace — the base table, so adding a family can only widen coverage. Values
still come exclusively from the candidate's own profile/QA answers; these
tables never introduce new answers, only new ways to recognise a field.
"""
from __future__ import annotations

_BASE_KEYS: dict[str, list[str]] = {
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

_FAMILY_KEYS: dict[str, dict[str, list[str]]] = {
    "workable": {
        "portfolio": ["portfolio_url", "portfolio"],
        "website": ["portfolio_url", "website"],
        "address": ["city", "location"],
        "notice period": ["availability", "start_date"],
        "préavis": ["availability", "start_date"],
    },
    "personio": {
        # Personio forms are common in DACH and often keep German labels even
        # for French postings.
        "vorname": ["first_name"],
        "nachname": ["last_name"],
        "e-mail-adresse": ["email"],
        "telefonnummer": ["phone"],
        "verfügbar": ["start_date", "availability"],
        "eintrittsdatum": ["start_date", "availability"],
        "gehaltsvorstellung": ["salary_expectation"],
        "portfolio": ["portfolio_url"],
    },
    "recruitee": {
        "téléphone portable": ["phone"],
        "site personnel": ["portfolio_url"],
        "portfolio": ["portfolio_url"],
        "disponibilité": ["start_date", "availability"],
        "date de disponibilité": ["start_date", "availability"],
    },
    "smartrecruiters": {
        "given name": ["first_name"],
        "family name": ["last_name"],
        "portfolio": ["portfolio_url"],
        "website": ["portfolio_url"],
    },
}


def heuristic_keys_for(ats: str) -> dict[str, list[str]]:
    """Base label-synonym table extended with the family-specific entries."""
    merged = dict(_BASE_KEYS)
    merged.update(_FAMILY_KEYS.get((ats or "").lower(), {}))
    return merged
