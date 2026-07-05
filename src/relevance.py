"""Shared AI-labor relevance heuristics used by ranking and the dashboard.

An article is considered on-topic when it carries BOTH an AI/automation signal
and a labor/work signal. Generic AI product news (no labor angle) and general
labor news (no AI angle) score low so they can be filtered or deprioritized.
"""

from __future__ import annotations

import re

AI_SIGNAL = re.compile(
    r"(?<!\w)("
    r"ai|a\.i\.|artificial intelligence|machine learning|generative ai|"
    r"chatgpt|gpt-\d|openai|chatbots?|llms?|large language models?|copilot|"
    r"deepfakes?|automations?|automated|automating|robots?|robotics?|robotic|"
    r"algorithms?|algorithmic|self-driving|autonomous|facial recognition"
    r")(?!\w)",
    re.I,
)

LABOR_SIGNAL = re.compile(
    r"(?<!\w)("
    r"labor|labour|jobs?|employment|unemployment|employees?|employers?|"
    r"workers?|workforce|workplaces?|wages?|salar(?:y|ies)|hiring|"
    r"layoffs?|laid off|job cuts?|job losses|redundanc(?:y|ies)|redundant|"
    r"unions?|strikes?|gig economy|gig workers?|freelancers?|freelance|"
    r"occupations?|professions?|careers?|reskill(?:ing)?|upskill(?:ing)?|"
    r"retrain(?:ing)?|staffing|recruiters?|recruit(?:ing|ment)?|payroll|"
    r"outsourc(?:e|ed|ing)|human resources|collective bargaining|severance|"
    r"voice actors?|garment workers?|delivery drivers?|call cent(?:er|re)s?|"
    r"labour economics|working conditions|"
    # Occupations that signal a labor angle when AI is also present.
    r"engineers?|programmers?|coders?|accountants?|paralegals?|translators?|"
    r"copywriters?|journalists?|teachers?|nurses?|cashiers?|receptionists?|"
    r"truck drivers?|customer service"
    r")(?!\w)",
    re.I,
)


def _unique_hits(pattern: re.Pattern, text: str) -> set[str]:
    return {m.lower() for m in pattern.findall(text or "")}


def has_ai_signal(text: str) -> bool:
    return bool(AI_SIGNAL.search(text or ""))


def has_labor_signal(text: str) -> bool:
    return bool(LABOR_SIGNAL.search(text or ""))


def is_labor_relevant(text: str) -> bool:
    """True when the text has both an AI signal and a labor signal."""
    return has_ai_signal(text) and has_labor_signal(text)


def relevance_score(headline: str, body: str = "") -> int:
    """Heuristic 0-100 relevance to AI's impact on work.

    Articles with both AI and labor signals always outrank one-sided articles:
    co-occurrence scores start at 45, one-sided articles cap at 45.
    """
    headline = headline or ""
    full = f"{headline} {body or ''}"

    ai_hits = _unique_hits(AI_SIGNAL, full)
    labor_hits = _unique_hits(LABOR_SIGNAL, full)
    if not ai_hits and not labor_hits:
        return 0

    score: int
    if ai_hits and labor_hits:
        score = 45
        score += min(len(labor_hits) * 5, 20)
        score += min(len(ai_hits) * 4, 12)
        if LABOR_SIGNAL.search(headline):
            score += 10
        if AI_SIGNAL.search(headline):
            score += 8
        return min(score, 100)

    # One-sided: rank by term density but stay below any co-occurring article.
    hits = labor_hits or ai_hits
    score = 15 + min(len(hits) * 5, 20)
    if (LABOR_SIGNAL if labor_hits else AI_SIGNAL).search(headline):
        score += 10
    return min(score, 45)
