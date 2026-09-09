from ai_news_share import nyt

DOC = {
    "headline": {"main": "OpenAI Unveils New Model"},
    "abstract": "The company said the system rivals human experts.",
    "pub_date": "2024-05-13T20:00:00+0000",
    "print_page": "1",
    "print_section": "A",
    "document_type": "article",
    "section_name": "Technology",
    "keywords": [{"value": "Artificial Intelligence"}],
    "web_url": "https://www.nytimes.com/x",
}


def test_page_one_filter():
    assert nyt.is_page_one(DOC)
    assert nyt.is_page_one({**DOC, "document_type": "Article"})  # capitalized since 2025
    assert not nyt.is_page_one({**DOC, "print_page": "12"})
    assert not nyt.is_page_one({**DOC, "print_page": None})
    assert not nyt.is_page_one({**DOC, "document_type": "multimedia"})


def test_front_page_is_section_a():
    assert nyt.is_front_page(nyt.item_from_doc(DOC))
    assert not nyt.is_front_page(nyt.item_from_doc({**DOC, "print_section": "B"}))


def test_item_classification():
    it = nyt.item_from_doc(DOC)
    assert it["date"] == "2024-05-13"
    assert it["topics"]["ai"] is True
    assert it["topics"]["covid"] is False


def test_months_iteration():
    from datetime import date

    ms = list(nyt.months(date(2019, 11, 15), date(2020, 2, 1)))
    assert ms == [(2019, 11), (2019, 12), (2020, 1), (2020, 2)]
