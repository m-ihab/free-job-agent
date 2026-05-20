"""France/Paris-focused job discovery helpers.

This module intentionally avoids scraping logged-in job boards.  It provides:
- safe search URL generation for French job boards and CAC 40 career pages
- France/Paris default data/AI queries
- a curated, editable list of CAC 40 target companies/career pages
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, quote_plus


DEFAULT_FRANCE_DATA_AI_QUERIES = [
    "data scientist stage",
    "machine learning internship",
    "data analyst stage",
    "data engineer stage",
    "AI intern",
    "intelligence artificielle stage",
    "alternance data science",
    "alternance machine learning",
    "junior data scientist",
    "chargé d'études data",
]

PARIS_LOCATION_ALIASES = {"paris", "paris 75", "ile-de-france", "île-de-france", "idf", "75"}


@dataclass(frozen=True)
class SearchBoard:
    key: str
    name: str
    url_template: str
    notes: str = ""

    def url(self, query: str, location: str = "Paris") -> str:
        return self.url_template.format(q=quote_plus(query), loc=quote_plus(location))


FRENCH_SEARCH_BOARDS: list[SearchBoard] = [
    SearchBoard(
        "france-travail-web",
        "France Travail web search",
        "https://candidat.francetravail.fr/offres/recherche?motsCles={q}&lieux=75D",
        "Manual fallback when API credentials are not configured.",
    ),
    SearchBoard(
        "welcome-to-the-jungle",
        "Welcome to the Jungle",
        "https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery={loc}",
        "No free public applicant API found; use manual import/add url.",
    ),
    SearchBoard(
        "hellowork",
        "HelloWork",
        "https://www.hellowork.com/fr-fr/emploi/recherche.html?k={q}&l={loc}",
        "Public web search URL only; no free applicant API implemented.",
    ),
    SearchBoard(
        "apec",
        "Apec",
        "https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={q}&lieux={loc}",
        "Useful for cadres/junior professional roles.",
    ),
    SearchBoard(
        "indeed-fr",
        "Indeed France",
        "https://fr.indeed.com/jobs?q={q}&l={loc}",
        "Partner APIs are not a free personal search/apply API.",
    ),
    SearchBoard(
        "linkedin-fr",
        "LinkedIn Jobs France",
        "https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}",
        "Manual browser search only; avoid logged-in automation.",
    ),
    SearchBoard(
        "glassdoor-fr",
        "Glassdoor France",
        "https://www.glassdoor.fr/Emploi/{loc}-{q}-emplois-SRCH_IL.0,5_IC2881970_KO6,26.htm",
        "Search URL can be brittle; use as manual fallback.",
    ),
    SearchBoard(
        "stage-fr",
        "Stage.fr",
        "https://www.stage.fr/jobs/?q={q}&l={loc}",
        "Manual internship-board search.",
    ),
    SearchBoard(
        "jobteaser",
        "JobTeaser",
        "https://www.jobteaser.com/fr/job-offers?query={q}&location={loc}",
        "Manual student/internship search; may require school account.",
    ),
    SearchBoard(
        "la-bonne-alternance",
        "La bonne alternance",
        "https://labonnealternance.apprentissage.beta.gouv.fr/recherche-emploi?display=list&job_name={q}&place={loc}",
        "Best for alternance/apprentissage manual fallback.",
    ),
]


@dataclass(frozen=True)
class CompanyTarget:
    name: str
    sector: str
    careers_url: str
    search_hint: str = "data science OR machine learning OR AI OR data analyst"


# Editable starter list based on commonly tracked CAC 40 constituents in 2026.
# Keep this as a target list, not a financial-data source of truth.
CAC40_TARGETS: list[CompanyTarget] = [
    CompanyTarget("Accor", "Hospitality", "https://careers.accor.com/"),
    CompanyTarget("Air Liquide", "Industrial gases", "https://www.airliquide.com/careers"),
    CompanyTarget("Airbus", "Aerospace", "https://www.airbus.com/en/careers"),
    CompanyTarget("ArcelorMittal", "Steel", "https://corporate.arcelormittal.com/careers"),
    CompanyTarget("AXA", "Insurance", "https://careers.axa.com/"),
    CompanyTarget("BNP Paribas", "Banking", "https://group.bnpparibas/en/careers"),
    CompanyTarget("Bouygues", "Construction/telecom/media", "https://www.bouygues.com/en/careers/"),
    CompanyTarget("Bureau Veritas", "Testing/certification", "https://careers.bureauveritas.com/"),
    CompanyTarget("Capgemini", "IT services", "https://www.capgemini.com/careers/"),
    CompanyTarget("Carrefour", "Retail", "https://recrute.carrefour.fr/"),
    CompanyTarget("Crédit Agricole", "Banking", "https://www.credit-agricole.com/en/careers"),
    CompanyTarget("Danone", "Food", "https://careers.danone.com/"),
    CompanyTarget("Dassault Systèmes", "Software", "https://www.3ds.com/careers"),
    CompanyTarget("Eiffage", "Construction/concessions", "https://www.eiffage.com/en/careers"),
    CompanyTarget("Engie", "Energy", "https://jobs.engie.com/"),
    CompanyTarget("EssilorLuxottica", "Optics", "https://careers.essilorluxottica.com/"),
    CompanyTarget("Eurofins Scientific", "Laboratory services", "https://careers.eurofins.com/"),
    CompanyTarget("Euronext", "Financial markets", "https://www.euronext.com/en/about/careers"),
    CompanyTarget("Hermès", "Luxury", "https://talents.hermes.com/"),
    CompanyTarget("Kering", "Luxury", "https://www.kering.com/en/talent/job-offers/"),
    CompanyTarget("Legrand", "Electrical equipment", "https://legrandgroup.com/en/careers"),
    CompanyTarget("L'Oréal", "Cosmetics", "https://careers.loreal.com/"),
    CompanyTarget("LVMH", "Luxury", "https://www.lvmh.com/talents/work-with-us/job-offers/"),
    CompanyTarget("Michelin", "Tires/mobility", "https://jobs.michelin.com/"),
    CompanyTarget("Orange", "Telecom", "https://orange.jobs/jobs/"),
    CompanyTarget("Pernod Ricard", "Beverages", "https://www.pernod-ricard.com/en/careers"),
    CompanyTarget("Publicis Groupe", "Communications", "https://careers.publicisgroupe.com/"),
    CompanyTarget("Renault Group", "Automotive", "https://www.renaultgroup.com/en/our-company/careers/"),
    CompanyTarget("Safran", "Aerospace/defense", "https://www.safran-group.com/jobs"),
    CompanyTarget("Saint-Gobain", "Materials", "https://joinus.saint-gobain.com/"),
    CompanyTarget("Sanofi", "Healthcare", "https://jobs.sanofi.com/"),
    CompanyTarget("Schneider Electric", "Energy management", "https://www.se.com/ww/en/about-us/careers/"),
    CompanyTarget("Société Générale", "Banking", "https://careers.societegenerale.com/"),
    CompanyTarget("STMicroelectronics", "Semiconductors", "https://stmicroelectronics.eightfold.ai/careers"),
    CompanyTarget("Stellantis", "Automotive", "https://careers.stellantis.com/"),
    CompanyTarget("Thales", "Defense/aerospace", "https://careers.thalesgroup.com/"),
    CompanyTarget("TotalEnergies", "Energy", "https://careers.totalenergies.com/"),
    CompanyTarget("Unibail-Rodamco-Westfield", "Real estate", "https://www.urw.com/en/careers"),
    CompanyTarget("Veolia", "Environmental services", "https://www.veolia.com/en/careers"),
    CompanyTarget("Vinci", "Construction/concessions", "https://jobs.vinci.com/"),
]


def build_france_search_urls(query: str, location: str = "Paris", boards: list[str] | None = None) -> list[tuple[str, str, str]]:
    """Return (key, board name, URL) for manual job-board searches."""
    allowed = {b.casefold() for b in boards} if boards else None
    rows: list[tuple[str, str, str]] = []
    for board in FRENCH_SEARCH_BOARDS:
        if allowed and board.key.casefold() not in allowed and board.name.casefold() not in allowed:
            continue
        rows.append((board.key, board.name, board.url(query, location)))
    return rows


def board_notes() -> dict[str, str]:
    return {board.key: board.notes for board in FRENCH_SEARCH_BOARDS}


def cac40_targets(limit: int | None = None) -> list[CompanyTarget]:
    return CAC40_TARGETS if limit is None else CAC40_TARGETS[:limit]
