from __future__ import annotations

import json
import os
import logging

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    return OpenAI()


def extract_experiences(text: str) -> dict:
    """
    Return JSON dict:
    {
      "experiences": [
        {"polarity","activity_type","place_mentions","summary","confidence","recommendation_score","evidence"},
        ...
      ]
    }
    """
    instructions = """
You extract TRAVEL EXPERIENCES from Reddit text.

Return ONLY valid JSON. No prose, no markdown.

If no valid experiences are found, return:
{"experiences": []}

====================
DEFINITION
====================
An experience is a concrete, first-hand, actionable statement describing something the author did at a specific, named Point of Interest (POI).

A valid experience MUST:
- Mention at least one specific POI by proper name.
- Describe a concrete action taken at that POI (e.g. ate, stayed, visited, soaked, bought).
- Be based on real experience, not plans, questions, or hypotheticals.

Exclude experiences that:
- Mention only broad or administrative areas (e.g. "Kyoto", "Tokyo", "Shibuya", "Iya Valley").
- Use only generic nouns (e.g. "a ramen shop", "a temple", "a bar").
- Refer to chain retail or convenience stores (e.g. Uniqlo, GU, 7-Eleven, Lawson, FamilyMart).
- Do not clearly identify the POI name.

If the POI name is ambiguous, incomplete, or uncertain, EXCLUDE the experience entirely.

====================
OUTPUT SCHEMA
====================
{
  "experiences": [
    {
      "polarity": "positive | negative | neutral",
      "activity_type": "restaurant | cafe | bar | onsen | museum | hotel | landmark | shop | activity | other",
      "place_mentions": ["Proper POI Name"],
      "summary": "<= 220 characters, factual, neutral tone, no hype>",
      "confidence": 0.0-1.0,
      "recommendation_score": 0-10,
      "evidence": ["short verbatim quote", "short verbatim quote"]
    }
  ]
}

====================
FIELD RULES
====================

polarity:
- positive: clearly favorable experience
- negative: clearly unfavorable experience
- neutral: factual description with little or no sentiment

activity_type:
- Choose the most specific applicable type.
- Use "other" only if none apply.

place_mentions:
- Must contain only proper names or distinct official labels.
- Do not include uncertain, partial, or inferred names.
- At least one entry is required for a valid experience.

summary:
- Max 220 characters.
- Describe the specific action at the POI.
- Factual, descriptive, no promotional language.

confidence:
- Your certainty that the experience is real, specific, and correctly extracted.
- 1.0 = explicit, unambiguous first-hand experience
- 0.5 = some ambiguity but still credible

recommendation_score:
- How compelling the recommendation is overall.
- Anchors:
  - 0-3: avoid / weak / negative
  - 4-6: mixed or average
  - 7-10: strong recommendation

evidence:
- 1-2 short verbatim snippets from the text.
- Each snippet ≤ 20 words.
- No URLs, no paraphrasing.

====================
STRICT RULES
====================
- Do NOT infer experiences not explicitly described.
- Do NOT hallucinate POI names.
- Do NOT include commentary outside the JSON.
- Output must be valid JSON and match the schema exactly.
""".strip()

    try:
        resp = _client().responses.create(
            model=OPENAI_MODEL,
            reasoning={"effort": "low"},
            instructions=instructions,
            input=[{"type": "message", "role": "user", "content": text}],
        )

        output = resp.output_text.strip()

        # Try to extract JSON from markdown code blocks if present
        if output.startswith("```"):
            # Remove markdown code fences
            lines = output.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            output = "\n".join(lines).strip()

        return json.loads(output)

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        logger.error(f"LLM output was: {resp.output_text[:500]}")
        # Return empty result on parse failure
        return {"experiences": []}

    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        return {"experiences": []}
