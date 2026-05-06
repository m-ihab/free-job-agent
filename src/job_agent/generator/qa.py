"""Answer screening questions using the QA profile."""
from __future__ import annotations

from rapidfuzz import fuzz

from job_agent.schemas.candidate import CandidateProfile, QAProfile

MANUAL_REVIEW_MARKER = "[MANUAL REVIEW REQUIRED - see master_qa_profile.json]"
MATCH_THRESHOLD = 70


def answer_screening_questions(
    questions: list[str],
    qa_profile: QAProfile,
    profile: CandidateProfile,
) -> dict[str, str]:
    """
    Match questions to locked QA entries using fuzzy matching.
    Returns {question: answer}.  Unmatched questions get the manual review marker.
    Only uses answers from qa_profile — never invents anything.
    """
    locked_entries = [e for e in qa_profile.entries if e.locked]
    answers: dict[str, str] = {}

    for question in questions:
        best_score = 0
        best_answer = MANUAL_REVIEW_MARKER
        for entry in locked_entries:
            score = fuzz.partial_ratio(
                entry.question_pattern.lower(), question.lower()
            )
            if score >= MATCH_THRESHOLD and score > best_score:
                best_score = score
                best_answer = entry.answer
        answers[question] = best_answer

    return answers
