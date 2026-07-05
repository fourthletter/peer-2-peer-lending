from src.relevance import is_labor_relevant, relevance_score


def test_requires_both_ai_and_labor_signals():
    assert is_labor_relevant("AI chatbot replaces call center workers")
    assert not is_labor_relevant("New AI chatbot writes poems and plans trips")
    assert not is_labor_relevant("Retail staff strike over wages and hiring freeze")


def test_ai_word_boundary():
    # "ai" must be a standalone word, not a fragment of another word.
    assert not is_labor_relevant("Air travel jobs in Thailand for workers")


def test_co_occurring_articles_outrank_one_sided():
    on_topic = relevance_score(
        "AI layoffs hit tech workers",
        "Automation is replacing jobs across the industry.",
    )
    ai_only = relevance_score(
        "OpenAI launches new model",
        "The chatbot is faster and cheaper than before.",
    )
    labor_only = relevance_score(
        "Union strike over wages",
        "Workers demand higher wages and more hiring.",
    )
    assert on_topic > ai_only
    assert on_topic > labor_only


def test_headline_signals_boost_score():
    in_headline = relevance_score("AI automation cuts warehouse jobs", "")
    in_body_only = relevance_score(
        "Quarterly report published", "AI automation cuts warehouse jobs"
    )
    assert in_headline > in_body_only


def test_zero_when_no_signals():
    assert relevance_score("Local team wins football match", "Great game.") == 0
