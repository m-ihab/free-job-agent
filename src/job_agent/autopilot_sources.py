"""Known CAC40 / large-French employer ATS slugs swept by the autopilot.

Each entry is the best-known combination of public ATS source + slug for that
employer. The autopilot auto-disables a slug for 24 h after it 404s, so a wrong
guess here is self-healing rather than fatal. Use ``job-agent validate-sources``
(or the UI button) to probe everything in one go.
"""
from __future__ import annotations


# Each entry below was probed live and returned HTTP 200 at the time of
# writing. Slugs that stop responding are auto-disabled for 24 h via the
# ``broken_sources`` table; run "Validate sources" in the UI to re-check.
CAC40_ATS_SLUGS: list[tuple[str, str, str]] = [
    # (source, slug, display name)

    # ---- Greenhouse (FR / EU scale-ups) ----
    ("greenhouse", "doctolib", "Doctolib"),
    ("greenhouse", "datadog", "Datadog"),
    ("greenhouse", "shifttechnology", "Shift Technology"),
    ("greenhouse", "algolia", "Algolia"),
    ("greenhouse", "mirakl", "Mirakl"),
    ("greenhouse", "thefork", "TheFork"),
    ("greenhouse", "getyourguide", "GetYourGuide"),
    ("greenhouse", "sumup", "SumUp"),
    ("greenhouse", "cognism", "Cognism"),
    ("greenhouse", "pleo", "Pleo"),
    ("greenhouse", "iterable", "Iterable"),

    # ---- Lever (FR data/AI scale-ups) ----
    ("lever", "scaleway", "Scaleway"),
    ("lever", "blablacar", "BlaBlaCar"),
    ("lever", "ledger", "Ledger"),
    ("lever", "swile", "Swile"),
    ("lever", "qonto", "Qonto"),
    ("lever", "mistral", "Mistral AI"),
    ("lever", "aircall", "Aircall"),
    ("lever", "voodoo", "Voodoo"),
    ("lever", "pennylane", "Pennylane"),
    ("lever", "malt", "Malt"),
    ("lever", "agicap", "Agicap"),
    ("lever", "pigment", "Pigment"),

    # ---- SmartRecruiters (CAC 40 traditional employers) ----
    ("smartrecruiters", "Capgemini", "Capgemini"),
    ("smartrecruiters", "AccorHotels", "Accor"),
    ("smartrecruiters", "LVMH", "LVMH"),
    ("smartrecruiters", "VeoliaEnvironment", "Veolia"),
    ("smartrecruiters", "Carrefour", "Carrefour"),
    ("smartrecruiters", "Bouygues", "Bouygues"),
    ("smartrecruiters", "Engie", "Engie"),
    ("smartrecruiters", "SchneiderElectric", "Schneider Electric"),
    ("smartrecruiters", "Orange", "Orange"),
    ("smartrecruiters", "Renaultgroup", "Renault"),
    ("smartrecruiters", "Sanofi", "Sanofi"),
    ("smartrecruiters", "PernodRicard", "Pernod Ricard"),
    ("smartrecruiters", "Airbus", "Airbus"),
    ("smartrecruiters", "Vinci", "Vinci"),
    ("smartrecruiters", "Stellantis", "Stellantis"),
    ("smartrecruiters", "Saint-Gobain", "Saint-Gobain"),
    ("smartrecruiters", "Michelin", "Michelin"),
    ("smartrecruiters", "L-Oreal", "L'Oréal"),
    ("smartrecruiters", "TotalEnergies", "TotalEnergies"),
    ("smartrecruiters", "Danone", "Danone"),
]
