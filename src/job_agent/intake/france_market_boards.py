"""Curated French job-board search URLs and CAC 40 career-page targets.

Data + the two frozen dataclasses they populate. No scraping of logged-in
boards — these are safe public search-URL templates only. Imported and
re-exported by :mod:`job_agent.intake.france_market`.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class SearchBoard:
    key: str
    name: str
    url_template: str
    notes: str = ""
    recommended: bool = True

    def url(self, query: str, location: str = "Paris") -> str:
        return self.url_template.format(q=quote_plus(query), loc=quote_plus(location))


FRENCH_SEARCH_BOARDS: list[SearchBoard] = [
    SearchBoard(
        "france-travail-web",
        "France Travail web search",
        "https://candidat.francetravail.fr/offres/recherche?motsCles={q}&lieux=75D",
        "Manual web search fallback; use API search for imported France Travail jobs.",
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
        "lesjeudis",
        "Les Jeudis",
        "https://www.lesjeudis.com/offres-emploi?mots={q}&lieu={loc}",
        "French IT/tech specialist job board — manual search, no public applicant API.",
    ),
    SearchBoard(
        "chooseparisregion",
        "Choose Paris Region",
        "https://chooseparisregion.org/en/talent/find-a-job?search={q}",
        "Paris Region international talent portal — English-language listings for the Paris ecosystem.",
    ),
    SearchBoard(
        "apec",
        "Apec",
        "https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={q}&lieux={loc}",
        "Useful for cadres/junior professional roles.",
    ),
    SearchBoard(
        "indeed-fr-stage",
        "Indeed France · Stages",
        "https://fr.indeed.com/jobs?q={q}&l={loc}&jt=internship",
        "Indeed internship filter — heavily used by French employers.",
    ),
    SearchBoard(
        "indeed-fr-alternance",
        "Indeed France · Alternance",
        "https://fr.indeed.com/jobs?q={q}+alternance&l={loc}",
        "Indeed alternance shortcut.",
    ),
    SearchBoard(
        "indeed-fr",
        "Indeed France",
        "https://fr.indeed.com/jobs?q={q}&l={loc}",
        "Indeed general search — broad fallback.",
        recommended=False,
    ),
    SearchBoard(
        "monster-fr",
        "Monster France",
        "https://www.monster.fr/emploi/recherche/?q={q}&where={loc}",
        "Generalist French job board with broad listings.",
        recommended=False,
    ),
    SearchBoard(
        "wttj-data",
        "Welcome to the Jungle · Data",
        "https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery={loc}&refinementList%5Bcontract_type%5D%5B%5D=apprenticeship&refinementList%5Bcontract_type%5D%5B%5D=internship",
        "Welcome to the Jungle pre-filtered to alternance + stage contracts.",
    ),
    SearchBoard(
        "talent-io",
        "Talent.io",
        "https://www.talent.io/jobs?role={q}&country=france",
        "Curated tech listings; manual browsing.",
        recommended=False,
    ),
    SearchBoard(
        "404partout",
        "404Partout",
        "https://www.404partout.fr/?keyword={q}",
        "Bilingual tech roles aggregator.",
        recommended=False,
    ),
    SearchBoard(
        "jobs-that-data",
        "Jobs That Data",
        "https://jobsthatdata.com/?q={q}&location={loc}",
        "Data-only job aggregator.",
        recommended=False,
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
        recommended=False,
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
        recommended=False,
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
