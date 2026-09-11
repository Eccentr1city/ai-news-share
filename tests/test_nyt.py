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


def test_write_unions_search_items_by_url(tmp_path):
    import json
    from datetime import date
    archive_item = nyt.item_from_doc({**DOC, "web_url": "https://nyt.test/a"})
    dup = nyt.item_from_doc({**DOC, "web_url": "https://nyt.test/a", "headline": {"main": "Same article, search copy"}})
    new = nyt.item_from_doc({**DOC, "web_url": "https://nyt.test/b", "pub_date": "2024-05-14T01:00:00+0000"})
    (tmp_path / "nyt_search.json").write_text(json.dumps({"2024-05-14": {"complete": True, "items": [dup, new]}}))
    nyt._write({"2024-05": [archive_item]}, {"2024-05"}, tmp_path / "nyt_items.jsonl", tmp_path / "nyt_daily.json")
    rows = [json.loads(l) for l in (tmp_path / "nyt_items.jsonl").read_text().splitlines()]
    assert sorted(r["url"] for r in rows) == ["https://nyt.test/a", "https://nyt.test/b"]
    assert [r for r in rows if r["url"].endswith("/a")][0]["headline"] == "OpenAI Unveils New Model"  # archive wins
    daily = json.loads((tmp_path / "nyt_daily.json").read_text())["daily"]
    assert daily["2024-05-13"]["n"] == 1 and daily["2024-05-14"]["n"] == 1
