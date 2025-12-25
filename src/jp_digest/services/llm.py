from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    return OpenAI()


def extract_experiences(text: str, bases: list[dict[str, list[str]]]) -> dict:
    """
    Return JSON dict:
    {
      "mentions": [
        {
          "entity_name",
          "entity_type",
          "experience_text",
          "recommendation_score",
          "location_hint",
          "location_confidence",
          "evidence_spans",
          "negative_or_caution",
          "canonicalization_hint",
          "assigned_base",
          "assigned_base_confidence"
        },
        ...
      ]
    }
    """
    base_names = [b["name"] for b in bases]
    base_list = "\n".join(
        f"- {b['name']} (aliases/kanji: {', '.join(b.get('aliases') or ['-'])})"
        for b in bases
    )
    base_enum = " | ".join(base_names + ["Unknown"])

    instructions = f"""
You extract EXPERIENCE MENTIONS from Reddit text.

Return ONLY valid JSON. No prose, no markdown.

If no valid mentions are found, return:
{{"mentions": []}}

====================
DEFINITION
====================
An experience mention is a concrete, actionable statement describing
something the author did OR explicitly recommends doing at a specific named entity
in Japan. The entity must be a named place (not just a city or neighborhood).

A valid mention MUST:
- Describe a concrete action taken or recommended at that entity (e.g. eat, stay, visit, soak, buy).
- Include a location_hint with geographic context (city/town/island/prefecture).
- Be based on real experience or a clear recommendation, not plans, questions, or hypotheticals.

Exclude mentions that:
- Do not specify any location or only name the country/continent (e.g. "Japan", "Asia").
- Use only generic nouns (e.g. "a ramen shop", "a temple", "a bar").
- Use generic location names as the entity (e.g. city/ward names like "Kyoto", "Shibuya").
- Are only plans, questions, or wishlists without a clear recommendation.

If the entity name is ambiguous, incomplete, or uncertain, exclude the mention.

====================
BASE LIST (IN ORDER)
====================
{base_list}

assigned_base must be one of: {base_enum}

====================
OUTPUT SCHEMA
====================
{{
  "mentions": [
    {{
      "entity_name": "Proper named entity (not a city)",
      "entity_type": "restaurant | cafe | bar | shop | onsen | museum | hike | hotel | landmark | activity | other",
      "experience_text": "1-2 sentences: what to do + why",
      "recommendation_score": 0-10,
      "location_hint": "Town/City/Island, Prefecture/Region",
      "location_confidence": 0.0-1.0,
      "evidence_spans": ["short verbatim quote", "short verbatim quote"],
      "negative_or_caution": "optional caution text or null",
      "canonicalization_hint": "optional canonical name or null",
      "assigned_base": "{base_enum}",
      "assigned_base_confidence": 0.0-1.0
    }}
  ]
}}

====================
FIELD RULES
====================

location_hint:
- Provide specific geographic context: Town/City/Island, Prefecture/Region
- For urban areas: Use "City, Ward/Neighborhood" (e.g., "Kyoto, Gion")
- For rural/island locations: Use "Town/Island, Prefecture" (e.g., "Naoshima, Kagawa" or "Oboke, Tokushima")
- For multi-location entities (hiking routes, bike routes): Use "Area/Route, Prefecture(s)" (e.g., "Shimanami Kaido, Hiroshima-Ehime")
- Always include prefecture/region for places outside major cities
- Do not return only "Japan" or a continent

experience_text:
- 1-2 sentences, factual, no hype.
- Describe the specific action or recommendation and why it stood out.

recommendation_score:
- 0-2: caution/avoid or clearly not recommended.
- 3-4: mixed or lukewarm.
- 5-6: neutral or mild recommendation.
- 7-8: strong recommendation with clear positives.
- 9-10: standout/must-do, repeated praise or emphatic endorsement.

entity_name:
- Must be a named place (not a city/ward/area).
- Do NOT output generic locations or base names.

entity_type:
- Choose the most specific applicable type.
- Use "activity" for multi-day routes, cycling routes, hiking trails.
- Use "other" only if none apply.

location_confidence:
- Your certainty that the location_hint is correct and complete.
- Use lower confidence (0.3-0.6) if only vague location context is given.

evidence_spans:
- 1-2 short verbatim snippets from the text.
- Each snippet <= 20 words.
- No URLs, no paraphrasing.

assigned_base:
- Assign to the CLOSEST base from the list based on geographic proximity.
- For entities between two bases, choose the one mentioned most in the text or the closer one.
- For multi-location routes/activities, assign to the base serving as the most logical starting point or hub.
- Examples:
  * Naoshima island → Takamatsu (ferry hub to art islands)
  * Shimanami Kaido → Matsuyama (Ehime end of route)
  * Iya Valley attractions → Iya Valley base
  * Oboke Gorge → Iya Valley (mountain region of Tokushima)
- If not near any base (>100km from all), use "Unknown" and exclude the mention.

assigned_base_confidence:
- How confident you are in the base assignment.
- Use high confidence (0.8-1.0) if the entity or its aliases appear in the base list.
- Use medium confidence (0.5-0.7) if geographic proximity is clear from context.
- Use lower confidence (0.3-0.5) if the entity could reasonably be accessed from multiple bases.

====================
STRICT RULES
====================
- Do NOT infer experiences not explicitly described.
- Do NOT hallucinate entity names.
- Do NOT invent a location_hint; if not supported by context, exclude the mention.
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
        return {"mentions": []}

    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        return {"mentions": []}
