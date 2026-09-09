"""Topic definitions: one keyword classifier + one GDELT query per topic.

Everything about *what counts as an AI story* lives here so it can be audited
and tuned in one place. The classifier is deliberately simple (regex on the
headline / item text plus its parent context) so the metric is reproducible
and cheap to backfill. See README for the calibration procedure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    pattern: re.Pattern
    gdelt_query: str
    color: str

    def matches(self, text: str) -> bool:
        return bool(self.pattern.search(text))


def _rx(*alts: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])", re.I)


AI = Topic(
    key="ai",
    label="AI",
    # Case-sensitive "AI"/"A.I." handled separately below via (?-i:...) group.
    pattern=re.compile(
        r"(?<![\w-])(?:"
        r"(?-i:AI|A\.I\.|AGI|LLMs?)"
        r"|artificial[ -]intelligence|artificial general intelligence|superintelligen\w*"
        r"|machine[ -]learning|deep[ -]learning|neural network\w*|large language model\w*"
        r"|language model\w*|foundation model\w*|generative (?:ai|model\w*)"
        r"|chatbots?|deepfakes?|autonomous (?:weapon|vehicle)s?|self-driving"
        r"|OpenAI|ChatGPT|GPT-?\d\w*|Anthropic|Claude \d|DeepMind|Gemini (?:\d|AI|model)|Google Gemini"
        r"|Nvidia|Copilot|Midjourney|Stable Diffusion|DALL[- ]E|Sora|DeepSeek|xAI|Grok|Mistral AI"
        r"|Sam Altman|Dario Amodei|Demis Hassabis|Geoffrey Hinton|Yoshua Bengio"
        r"|AlphaGo|AlphaFold|Waymo|Tesla Autopilot|Full Self-Driving"
        r")(?![\w-])",
        re.I,
    ),
    gdelt_query=(
        '("artificial intelligence" OR "generative AI" OR "AI model" OR "AI models" '
        'OR "AI company" OR "AI companies" OR "AI chatbot" OR "AI safety" OR "AI regulation" '
        'OR "AI systems" OR "AI industry" OR "AI tools" OR chatgpt OR openai OR anthropic '
        'OR deepmind OR "large language model" OR "machine learning")'
    ),
    color="#c2410c",
)

COVID = Topic(
    key="covid",
    label="Covid",
    # Deliberately specific: generic words (vaccine, quarantine, lockdown,
    # pandemic) also describe measles, Ebola and flu stories, which would give
    # Covid a spurious pre-2020 baseline. On Wikipedia the parent bullet
    # ("COVID-19 pandemic > ...") carries the topic for almost every item anyway.
    pattern=_rx(
        r"covid(?:-19)?", r"coronavirus\w*", r"sars-cov-2", r"2019-ncov", r"ncov",
        r"wuhan (?:virus|pneumonia|outbreak)", r"omicron", r"delta variant",
        r"pfizer(?:-biontech)?", r"moderna", r"astrazeneca", r"novavax",
    ),
    gdelt_query='(coronavirus OR covid OR "covid-19" OR "sars-cov-2" OR "wuhan virus" OR "wuhan pneumonia")',
    color="#1d4ed8",
)

CLIMATE = Topic(
    key="climate",
    label="Climate",
    pattern=_rx(
        r"climate change", r"global warming", r"greenhouse", r"carbon (?:emissions?|tax|neutral|dioxide)",
        r"net[- ]zero", r"COP ?\d\d", r"Paris (?:climate )?(?:agreement|accord)", r"IPCC", r"decarboni[sz]\w*",
        r"heat ?wave\w*", r"wildfires?", r"sea level", r"fossil fuels?",
    ),
    gdelt_query='("climate change" OR "global warming" OR "greenhouse gas" OR "carbon emissions" OR "net zero")',
    color="#15803d",
)

TOPICS: dict[str, Topic] = {t.key: t for t in (AI, COVID, CLIMATE)}


def classify(text: str) -> dict[str, bool]:
    return {k: t.matches(text) for k, t in TOPICS.items()}
