from datetime import date

from ai_news_share import wikipedia

OLD = """{{Current events|year=2020|month=03|day=11|content=
;Armed conflicts and attacks
*[[War in Afghanistan (2001–2021)|War in Afghanistan]]
**The [[Taliban]] rejects the order. [https://x.test/a (Al Jazeera)]
;Business and economy
*[[Economic impact of the COVID-19 pandemic]]
**Aftermath of [[2020 stock market crash|Black Monday]]
***The Dow plunges 1,400 points. [https://x.test/b (Fox News)]
;Science and technology
*[[OpenAI]] releases a new [[language model]]. [https://x.test/c (''The Verge'')]
}}"""

NEW = """{{Current events|year=2026|month=09|day=7|top=yes}}
'''Armed conflicts and attacks'''
*[[Middle Eastern crisis (2023–present)|Middle Eastern crisis]]
**[[2026 Iran war]]
***Oman's navy rescues 16 crew. [https://x.test/d (AP)]
'''Science and technology'''
*[[Anthropic]] releases Claude 6. [https://x.test/e (Reuters)]
*A study on [[deep learning]] is published. [https://x.test/f (Nature)]
"""


def test_parse_old_format_leaf_items_and_context():
    items = wikipedia.parse_day(date(2020, 3, 11), OLD)
    assert [i.text for i in items] == [
        "The Taliban rejects the order.",
        "The Dow plunges 1,400 points.",
        "OpenAI releases a new language model.",
    ]
    assert items[0].section == "Armed conflicts and attacks"
    assert items[1].context == "Economic impact of the COVID-19 pandemic > Aftermath of Black Monday"
    assert items[1].topics["covid"] is True  # classified via parent context
    assert items[0].topics["covid"] is False
    assert items[2].topics["ai"] is True
    assert items[2].sources == ["The Verge"]


def test_parse_new_format_sections():
    items = wikipedia.parse_day(date(2026, 9, 7), NEW)
    assert len(items) == 3
    assert items[0].section == "Armed conflicts and attacks"
    assert items[1].section == "Science and technology"
    assert [i.topics["ai"] for i in items] == [False, True, True]


def test_page_title_roundtrip():
    d = date(2020, 3, 5)
    assert wikipedia.page_title(d) == "Portal:Current events/2020 March 5"
    assert wikipedia.title_to_date(wikipedia.page_title(d)) == d
