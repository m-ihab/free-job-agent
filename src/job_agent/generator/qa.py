"""Answer screening questions using the locked QA profile."""
from __future__ import annotations

import re

from job_agent.schemas.candidate import CandidateProfile, QAProfile, QAEntry
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ScreeningAnswer
from job_agent.utils import fuzzy

MANUAL_REVIEW_MARKER = "[MANUAL REVIEW REQUIRED - add a locked answer to master_qa_profile.json]"
MATCH_THRESHOLD = 72


_QUESTION_PREFIX_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s*")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_QUESTION_LENGTH = 260


def _clean_possible_question(line: str) -> str:
    line = _QUESTION_PREFIX_RE.sub("", line.strip())
    line = _WHITESPACE_RE.sub(" ", line)
    return line.strip(" -\t")


def extract_screening_questions(text: str, limit: int = 20) -> list[str]:
    """Extract explicit screening/application questions from job text.

    This is intentionally conservative: it only returns text that already
    contains a question mark. It does not synthesize legal, visa, salary, or
    background-check answers from requirements.
    """
    questions: list[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = _clean_possible_question(raw_line)
        if not line or "?" not in line:
            continue
        for candidate in re.findall(r"[^?]{4,}\?", line):
            question = _WHITESPACE_RE.sub(" ", candidate).strip()
            if ":" in question:
                prefix, rest = question.split(":", 1)
                if any(term in prefix.casefold() for term in ("question", "screening", "application")) and "?" in rest:
                    question = rest.strip()
            if not (8 <= len(question) <= _MAX_QUESTION_LENGTH):
                continue
            key = question.casefold()
            if key in seen:
                continue
            questions.append(question)
            seen.add(key)
            if len(questions) >= limit:
                return questions
    return questions


def _entry_patterns(entry: QAEntry) -> list[str]:
    return [p for p in entry.question_patterns if p]


def _answer_to_text(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def best_locked_answer(question: str, qa_profile: QAProfile) -> ScreeningAnswer:
    """Return the best locked QA answer for a question, or manual-review marker."""
    best_score = 0
    best_entry: QAEntry | None = None
    for entry in qa_profile.locked_entries():
        for pattern in _entry_patterns(entry):
            score = fuzzy.partial_ratio(pattern.lower(), question.lower())
            if score > best_score:
                best_score = score
                best_entry = entry
    if best_entry is not None and best_score >= MATCH_THRESHOLD:
        return ScreeningAnswer(
            question=question,
            answer=_answer_to_text(best_entry.answer),
            source="master_qa_profile",
            confidence=min(1.0, best_score / 100),
            needs_review=False,
        )
    return ScreeningAnswer(
        question=question,
        answer=MANUAL_REVIEW_MARKER,
        source="manual_required",
        confidence=0.0,
        needs_review=True,
    )


def answer_screening_questions(
    questions: list[str],
    qa_profile: QAProfile,
    profile: CandidateProfile | None = None,
) -> dict[str, str]:
    """Backward-compatible dict API used by earlier tests/CLI."""
    return {q: best_locked_answer(q, qa_profile).answer for q in questions}


def answer_screening_questions_structured(
    questions: list[str],
    qa_profile: QAProfile,
) -> list[ScreeningAnswer]:
    return [best_locked_answer(q, qa_profile) for q in questions]


def standard_locked_answers(qa_profile: QAProfile) -> dict[str, str]:
    """Return standard locked answers for the manual assistant page.

    These are not auto-submitted; they give the user a safe copy/paste source.
    """
    answers: dict[str, str] = {}
    for entry in qa_profile.locked_entries():
        label = entry.question_patterns[0]
        answers[label] = _answer_to_text(entry.answer)
    return answers


def standard_locked_answers_structured(qa_profile: QAProfile) -> list[ScreeningAnswer]:
    return [
        ScreeningAnswer(
            question=entry.question_patterns[0],
            answer=_answer_to_text(entry.answer),
            source="master_qa_profile",
            confidence=1.0,
            needs_review=False,
        )
        for entry in qa_profile.locked_entries()
    ]


def build_screening_answers_for_job(
    job: JobListing,
    qa_profile: QAProfile,
    *,
    include_answer_bank: bool = True,
) -> list[ScreeningAnswer]:
    """Build safe screening answers for a job packet.

    Explicit questions found in the posting are answered from locked QA entries
    only. If no explicit questions are found, the locked answer bank is returned
    so the user has a copy/paste reference during manual submission. If explicit
    questions are found, the locked answer bank is appended after detected
    questions unless ``include_answer_bank`` is false.
    """
    detected = extract_screening_questions(job.raw_text or job.description or "")
    if not detected:
        return standard_locked_answers_structured(qa_profile)

    answers = answer_screening_questions_structured(detected, qa_profile)
    if not include_answer_bank:
        return answers

    seen = {a.question.casefold() for a in answers}
    for answer in standard_locked_answers_structured(qa_profile):
        key = answer.question.casefold()
        if key not in seen:
            answers.append(answer)
            seen.add(key)
    return answers


def screening_answers_to_dict(answers: list[ScreeningAnswer]) -> dict[str, str]:
    """Backward-compatible packet dictionary for prepared QA answers."""
    return {answer.question: answer.answer for answer in answers}

