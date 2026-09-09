import json

from ai_news_share import labels, llm_classify


def test_params_and_parse_roundtrip(tmp_path):
    chunk = [("k1", "AI boom > OpenAI releases GPT-6"), ("k2", "Floods kill 12 in Turkey")]
    p = llm_classify._params(chunk)
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert "[0] AI boom > OpenAI releases GPT-6" in p["messages"][0]["content"]
    rows = llm_classify._parse(chunk, json.dumps({"labels": [
        {"i": 0, "echo": "AI boom >", "ai": True, "covid": False, "climate": False},
        {"i": 1, "echo": "Floods kill 12", "ai": False, "covid": False, "climate": False},
        {"i": 7, "echo": "x y z", "ai": True, "covid": True, "climate": True},  # out of range: ignored
    ]}))
    assert [r["key"] for r in rows] == ["k1", "k2"]
    assert rows[0]["ai"] is True and rows[1]["ai"] is False


def test_parse_drops_misaligned_echo():
    chunk = [("k1", "OpenAI releases GPT-6"), ("k2", "Floods kill 12 in Turkey")]
    rows = llm_classify._parse(chunk, json.dumps({"labels": [
        {"i": 0, "echo": "Floods kill 12", "ai": False, "covid": False, "climate": False},  # shifted
        {"i": 1, "echo": "Floods kill 12", "ai": False, "covid": False, "climate": False},
    ]}))
    assert [r["key"] for r in rows] == ["k2"]


def test_label_cache_roundtrip(tmp_path):
    t = "Anthropic  releases Claude 6"
    labels.append(tmp_path, [{"key": labels.key_of(t), "ai": True, "covid": False, "climate": False, "model": "m", "text": t}])
    labels._cache = None  # force reload from disk
    assert labels.llm_topics(tmp_path, "anthropic releases claude 6") == {"ai": True, "covid": False, "climate": False}
    assert labels.llm_topics(tmp_path, "something else") is None


def test_add_llm_counts():
    row = {"n": 3, "ai": 1}
    labels.add_llm_counts(row, {"ai": True, "covid": False, "climate": False})
    labels.add_llm_counts(row, None)
    assert row["n_llm"] == 1 and row["ai_llm"] == 1 and row["covid_llm"] == 0
