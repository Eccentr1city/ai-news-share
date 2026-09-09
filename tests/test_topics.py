import pytest

from ai_news_share.topics import AI, COVID


@pytest.mark.parametrize(
    "text",
    [
        "OpenAI releases GPT-5",
        "The EU passes an AI Act",
        "Senators question Sam Altman about artificial intelligence",
        "Nvidia becomes most valuable company",
        "A deepfake of the president circulates",
    ],
)
def test_ai_positive(text):
    assert AI.matches(text)


@pytest.mark.parametrize(
    "text",
    [
        "Air Force jets scramble",  # 'AI' inside a word
        "Amnesty International said Tuesday",
        "Claude Monet exhibition opens",
        "The gemini constellation rises",
        "Hurricane Ai makes landfall",  # lowercase 'ai' is not the acronym
        "Thai protests continue",
    ],
)
def test_ai_negative(text):
    assert not AI.matches(text)


def test_covid():
    assert COVID.matches("Wuhan coronavirus outbreak spreads")
    assert COVID.matches("Aftermath of the COVID-19 pandemic")
    assert not COVID.matches("Flu season begins")
