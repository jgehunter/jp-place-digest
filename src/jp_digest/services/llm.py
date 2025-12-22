from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")


def _client() -> OpenAI:
    return OpenAI()


def extract_experiences(text: str) -> dict:
    """
    Return JSON dict:
    { "experiences": [ {polarity, activity_type, place_mentions, summary, confidence}, ...] }
    """
    instructions = (
        "You extract TRAVEL EXPERIENCES from Reddit text.\n"
        "Return ONLY valid JSON.\n"
        "\n"
        "Definition:\n"
        "- An experience is a concrete, actionable statement based on real experience.\n"
        "- Focus on specific restaurants, cafes, activities, hotels, landmarks.\n"
        "- Prefer proper nouns that are lookup-able on maps.\n"
        "- Exclude generic nounds (e.g. 'a ramen shop', 'a temple').\n"
        '- If no concrete experiences, return {"experiences": []}.\n'
        "\n"
        "Schema:\n"
        "{\n"
        '  "experiences": [\n'
        "    {\n"
        '      "polarity": "positive|negative|neutral",\n'
        '      "activity_type": "restaurant|cafe|activity|hotel|landmark|shop|other",\n'
        '      "place_mentions": ["..."],\n'
        '      "summary": "<= 220 chars, factual, no hype",\n'
        '      "confidence": 0.0-1.0\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        "Rules:\n"
        "- place_mentions must be proper names or distinct labels.\n"
        "- If uncertain about a name, do not include it.\n"
        "- If warning/avoid, set polarity=negative.\n"
    )

    # Fixed: Use proper message format for Responses API
    resp = _client().responses.create(
        model=OPENAI_MODEL,
        reasoning={"effort": "low"},
        instructions=instructions,
        input=[{"type": "message", "role": "user", "content": text}],
    )
    return json.loads(resp.output_text)
