"""Best-effort real-company extraction.

When a job aggregator (notably France Travail) reports itself as the
"employer" because the actual hirer is anonymised, we still want the cover
letter to address the real company. We scan the description / raw_text for
common patterns:

- "Dassault Systèmes seeks…", "Capgemini is hiring…", "Join L'Oréal…"
- "About <Company>:"
- "<Company> recrute / recherche / cherche"

If nothing reliable is found, we fall back to the aggregator's company name.
The function never invents a company that isn't in the source text.
"""
from __future__ import annotations

import re

from job_agent.schemas.job import JobListing


# Aggregators / shell names we should NEVER use as the company on a cover
# letter — they're not the actual employer.
AGGREGATOR_COMPANIES = {
    "france travail",
    "pole emploi",
    "pôle emploi",
    "ftv",
    "anonymous",
    "anonyme",
    "[to be parsed]",
    "confidential",
    "unknown",
    "indeed",
    "linkedin",
    "welcome to the jungle",
    "hellowork",
    "apec",
}

BAD_COMPANY_STARTS = {
    "vous", "notre", "nos", "votre", "le", "la", "les", "l", "au", "aux",
    "cette", "cet", "ce", "ces", "il", "elle", "nous", "on", "profil",
    "mission", "missions", "description", "poste",
}

BAD_COMPANY_FRAGMENTS = {
    "vous êtes", "vous etes", "le profil", "l'équipe",
    "l'equipe", "au sein", "notre client", "notre team", "business unit",
    "secteur", "en tant", "de la direction", "qu'on",
}

# Lightweight heuristic list of well-known French employers we want to
# recognize confidently when they appear in description text. The matcher
# is case-insensitive and uses word boundaries.
KNOWN_FRENCH_COMPANIES = [
    "Dassault Systèmes", "Dassault Systemes",
    "BNP Paribas", "Société Générale", "Societe Generale", "Crédit Agricole", "Credit Agricole",
    "AXA", "Allianz", "Orange", "Engie", "EDF", "TotalEnergies", "Total",
    "Capgemini", "Atos", "Sopra Steria", "CGI", "Accenture", "Wavestone", "Mazars",
    "L'Oréal", "L'Oreal", "LVMH", "Hermès", "Hermes", "Kering", "Chanel",
    "Renault", "Stellantis", "Peugeot", "Airbus", "Safran", "Thales", "Naval Group", "MBDA",
    "Sanofi", "Servier", "Pierre Fabre",
    "Schneider Electric", "Veolia", "Suez", "Bouygues", "Vinci", "Eiffage",
    "SNCF", "RATP", "Air France", "Aéroports de Paris", "ADP",
    "Carrefour", "Decathlon", "FNAC", "Darty",
    "Dassault Aviation", "Michelin",
    "Adobe", "Amazon", "Apple", "Google", "Meta", "Microsoft", "Oracle", "Salesforce",
    "Datadog", "Doctolib", "Mistral AI", "Hugging Face", "Stripe", "Criteo", "Spotify",
    "Qair", "Saint-Gobain", "Pernod Ricard", "Publicis", "Vivendi",
    "Mirakl", "Algolia", "Snowflake", "PwC", "EY", "KPMG", "Deloitte",
    "Histoire d'Or", "THOM", "Agence Nationale de la Recherche", "ANR", "ISCOD",
    "Bassetti Group", "Banque de France", "Keyrus",
]

_PATTERNS = [
    # "About <Company>", "Présentation de <Company>"
    re.compile(r"\b(?:about|presentation of|pr[ée]sentation de|chez)\s+([A-Z][A-Za-zÀ-ÿ0-9 .'’&\-]{2,40})", re.IGNORECASE),
    # "<Company> recrute|recherche|seeks|cherche|is hiring|is looking"
    re.compile(r"\b([A-Z][A-Za-zÀ-ÿ0-9 .'’&\-]{2,40})\s+(?:seeks|is hiring|is looking|recrute|recherche|cherche)\b"),
    # "rejoignez <Company>", "join <Company>"
    re.compile(r"\b(?:rejoignez|join)\s+([A-Z][A-Za-zÀ-ÿ0-9 .'’&\-]{2,40})\b"),
    # "for <Company>" inside positions like "Software Engineer for Capgemini"
    re.compile(r"\bfor\s+([A-Z][A-Za-zÀ-ÿ0-9 .'’&\-]{2,40})\b"),
]


def _looks_aggregator(name: str | None) -> bool:
    if not name:
        return True
    return name.strip().lower() in AGGREGATOR_COMPANIES


def looks_unusable_company(name: str | None) -> bool:
    """True for aggregators or sentence fragments saved as company names."""
    if _looks_aggregator(name):
        return True
    cleaned = (name or "").strip(" .,;:'\"").casefold()
    if not cleaned:
        return True
    if any(fragment in cleaned for fragment in BAD_COMPANY_FRAGMENTS):
        return True
    first = re.sub(r"[^a-zÃ -Ã¿]+", "", cleaned.split()[0] if cleaned.split() else "")
    if first in BAD_COMPANY_STARTS and not _scan_known(name or ""):
        return True
    return False


def _scan_known(haystack: str) -> str | None:
    matches: list[tuple[int, int, str]] = []
    for candidate in KNOWN_FRENCH_COMPANIES:
        pattern = re.compile(r"\b" + re.escape(candidate) + r"\b", re.IGNORECASE)
        match = pattern.search(haystack)
        if match:
            # Prefer the earliest employer-like mention, then the longest
            # name. This prevents later tool mentions (Snowflake, Salesforce)
            # from beating the actual company introduced in the first line.
            matches.append((match.start(), -len(candidate), candidate))
    return sorted(matches)[0][2] if matches else None


def _scan_patterns(haystack: str) -> str | None:
    for pattern in _PATTERNS:
        for match in pattern.finditer(haystack):
            candidate = (match.group(1) or "").strip(" .,;:'\"")
            if not candidate or len(candidate) > 60:
                continue
            if looks_unusable_company(candidate):
                continue
            # Must look like a proper company name (at least one capitalized
            # word; not just lowercase or punctuation).
            if not re.search(r"[A-ZÀ-Ý]", candidate):
                continue
            return candidate
    return None


def extract_real_company(job: JobListing) -> str | None:
    """Try to find the real employer when the listing reports an aggregator."""
    haystack = "\n".join([
        job.description or "",
        job.raw_text or "",
        job.title or "",
    ])
    if not haystack.strip():
        return None
    known = _scan_known(haystack)
    if known:
        return known
    return _scan_patterns(haystack)


def resolve_company_for_letter(job: JobListing) -> str:
    """Return the best company name to address in a cover letter.

    Logic:
    - If the source company is a known aggregator, search the description
      for a real employer and use that.
    - Otherwise keep the source company.
    - Last resort: return a polite "the hiring team" so the letter never
      says "Dear Hiring Manager at France Travail".
    """
    if not looks_unusable_company(job.company):
        return job.company
    real = extract_real_company(job)
    if real:
        return real
    return "the hiring team"
