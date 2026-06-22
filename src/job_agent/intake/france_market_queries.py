"""France/Paris data-AI query vocabularies and role-family expansion map.

Pure data, no logic. Imported by :mod:`job_agent.intake.france_market`, which
re-exports these names for backward compatibility.
"""
from __future__ import annotations


ROLE_QUERY_TERMS = [
    "data scientist",
    "data science",
    "machine learning",
    "AI",
    "artificial intelligence",
    "intelligence artificielle",
    "data analyst",
    "analyste data",
    "data engineer",
    "data engineering",
    "business intelligence",
    "BI analyst",
    "data automation",
]

ENGLISH_ROLE_QUERY_TERMS = [
    "data scientist",
    "data science",
    "machine learning",
    "AI",
    "artificial intelligence",
    "data analyst",
    "data engineer",
    "data engineering",
    "business intelligence",
    "BI analyst",
    "data automation",
]

FRENCH_ROLE_QUERY_TERMS = [
    "data scientist",
    "machine learning",
    "intelligence artificielle",
    "data analyst",
    "analyste data",
    "data engineer",
    "business intelligence",
    "data automation",
    "chargé d'études data",
]

INTERNSHIP_QUERY_TERMS = [
    "stage",
    "stagiaire",
    "intern",
    "internship",
    "alternance",
    "apprentissage",
    "apprenticeship",
    "junior",
    "graduate",
]

ENGLISH_INTERNSHIP_QUERY_TERMS = [
    "internship",
    "intern",
    "apprenticeship",
    "junior",
    "graduate",
]

FRENCH_INTERNSHIP_QUERY_TERMS = [
    "stage",
    "stagiaire",
    "alternance",
    "apprentissage",
]


DEFAULT_FRANCE_DATA_AI_QUERIES = [
    # ── Core bilingual pairs ─────────────────────────────────────────────────
    "stage data",
    "alternance data",
    "data scientist stage",
    "data science internship",
    "machine learning stage",
    "machine learning internship",
    "stagiaire machine learning",
    "data analyst stage",
    "stagiaire data analyst",
    "data engineer stage",
    "business intelligence stage",
    "data automation internship",
    "AI intern",
    "intelligence artificielle stage",
    "stage intelligence artificielle",
    "alternance data science",
    "alternance machine learning",
    "alternance data analyst",
    "apprentissage data",
    "junior data scientist",
    "graduate data scientist",
    "chargé d'études data",
    # ── Extended French internship/alternance terms ──────────────────────────
    "stage NLP",
    "alternance deep learning",
    "stage MLOps",
    "contrat pro data",
    "stage analyse de données",
    "stagiaire IA Paris",
    "stage LLM",
    "alternance NLP Paris",
    "stage modélisation",
    "stage IA générative",
    "apprenti data engineer",
    "stage computer vision",
    "alternance traitement données",
    "stage Python data",
    "VIE data science",
    "stagiaire science des données",
    "alternance big data",
    "stage traitement langage naturel",
    "stage apprentissage automatique",
    "contrat alternance data scientist",
    # ── English variants for bilingual boards ────────────────────────────────
    "data science internship Paris",
    "machine learning internship Paris",
    "AI internship France",
    "NLP internship",
    "deep learning intern",
    "MLOps intern",
    "LLM engineer intern",
    "data engineering internship",
    "computer vision internship",
]

PARIS_LOCATION_ALIASES = {"paris", "paris 75", "ile-de-france", "île-de-france", "idf", "75"}


# Role-family map: if a user seeds with one of these, expand to the related
# data/AI roles automatically. Keeps the user from having to know all variants.
ROLE_FAMILY_MAP: dict[str, list[str]] = {
    "data scientist": [
        "data scientist", "data science", "machine learning", "ml engineer",
        "ai engineer", "data analyst", "data engineer", "applied scientist",
    ],
    "data science": [
        "data science", "data scientist", "machine learning", "ml engineer",
        "ai engineer", "data analyst", "applied scientist",
    ],
    "machine learning": [
        "machine learning", "ml engineer", "mlops", "deep learning",
        "ai engineer", "data scientist", "applied ml",
    ],
    "ml engineer": [
        "ml engineer", "machine learning", "mlops", "ai engineer",
        "deep learning engineer",
    ],
    "ai engineer": [
        "ai engineer", "machine learning", "ml engineer", "ia engineer",
        "intelligence artificielle",
    ],
    "data analyst": [
        "data analyst", "business intelligence", "bi analyst", "analytics",
        "analyste data", "analytics engineer",
    ],
    "data engineer": [
        "data engineer", "data engineering", "etl", "analytics engineer",
        "mlops", "data platform",
    ],
    "business intelligence": [
        "business intelligence", "bi analyst", "data analyst",
        "analytics engineer", "power bi",
    ],
    "ia": [
        "intelligence artificielle", "ia engineer", "ai engineer",
        "machine learning", "data scientist",
    ],
    "nlp": [
        "NLP", "natural language processing", "traitement langage naturel",
        "text mining", "large language model", "LLM", "transformer",
    ],
    "deep learning": [
        "deep learning", "neural network", "computer vision", "NLP",
        "machine learning", "ml engineer",
    ],
    "llm": [
        "LLM", "large language model", "generative AI", "IA générative",
        "NLP", "deep learning", "ai engineer",
    ],
    "mlops": [
        "MLOps", "ml engineer", "data engineer", "model deployment",
        "machine learning", "devops data",
    ],
    "computer vision": [
        "computer vision", "image recognition", "deep learning",
        "vision par ordinateur", "machine learning",
    ],
}
