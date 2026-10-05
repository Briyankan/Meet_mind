"""
Meeting summarization and action item extraction via Google Gemini API.
"""

import logging
from typing import Any, Dict, List

from utils.gemini_client import GeminiError, generate_json_completion

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 28_000

SYSTEM_PROMPT = """You are a professional meeting analyst. Your job is to produce accurate,
factual meeting notes from transcripts only. Never invent speakers, decisions, or facts
not supported by the transcript. If information is unclear, say so briefly rather than guessing.
Output must be valid JSON matching the required schema exactly."""

SUMMARY_PROMPT_TEMPLATE = """Analyze the following meeting transcript and produce structured meeting notes.

RULES:
1. Use ONLY information present in the transcript.
2. Do NOT hallucinate names, decisions, or action items.
3. Do NOT invent speakers or attendees not mentioned.
4. Separate discussion points, decisions, and action items clearly.
5. Action items must be concrete tasks with assignee only if explicitly stated (otherwise empty string).
6. Preserve important numbers, dates, and deadlines mentioned.
7. If a section has no content in the transcript, use a short honest note like "Not explicitly stated in transcript."

Return JSON with this exact structure:
{{
  "meeting_overview": "2-4 sentence factual overview",
  "discussion_points": ["point 1", "point 2"],
  "key_decisions": ["decision 1"],
  "action_items": [
    {{"task": "description", "assignee": "name or empty", "due": "date or empty"}}
  ],
  "final_conclusion": "1-3 sentence wrap-up"
}}

TRANSCRIPT:
---
{transcript}
---
"""


def _truncate(text: str) -> str:
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    return text[:MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated for processing.]"


def _normalize_list(value: Any, fallback: List[str]) -> List[str]:
    if isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
        return items or fallback
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return fallback


def _normalize_actions(value: Any) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                items.append(
                    {
                        "task": str(entry.get("task", "")).strip(),
                        "assignee": str(entry.get("assignee", "")).strip(),
                        "due": str(entry.get("due", "")).strip(),
                    }
                )
            elif isinstance(entry, str) and entry.strip():
                items.append({"task": entry.strip(), "assignee": "", "due": ""})
    elif isinstance(value, str) and value.strip():
        items.append({"task": value.strip(), "assignee": "", "due": ""})

    items = [i for i in items if i["task"]]
    if not items:
        items = [
            {
                "task": "No explicit action items detected — review transcript for next steps.",
                "assignee": "",
                "due": "",
            }
        ]
    return items


def _format_action_display(actions: List[Dict[str, str]]) -> List[str]:
    formatted = []
    for item in actions:
        line = item["task"]
        if item.get("assignee"):
            line += f" (Assignee: {item['assignee']})"
        if item.get("due"):
            line += f" (Due: {item['due']})"
        formatted.append(line)
    return formatted


def generate_summary(transcript_text: str) -> Dict[str, Any]:
    """Generate structured meeting summary using Gemini."""
    if not transcript_text or not transcript_text.strip():
        raise ValueError("Transcript is empty. Please provide meeting text to summarize.")

    text = _truncate(transcript_text.strip())
    prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=text)

    try:
        raw = generate_json_completion(prompt=prompt, system=SYSTEM_PROMPT)
    except GeminiError:
        raise
    except Exception as exc:
        logger.exception("Summarization failed: %s", exc)
        raise RuntimeError("Summarization failed. Check your Gemini API key.") from exc

    overview = str(raw.get("meeting_overview") or raw.get("overview") or "").strip()
    discussion = _normalize_list(
        raw.get("discussion_points"),
        ["General discussion captured in the transcript."],
    )
    decisions = _normalize_list(
        raw.get("key_decisions") or raw.get("decisions"),
        ["No explicit decisions stated in the transcript."],
    )
    actions_raw = raw.get("action_items") or raw.get("actions") or []
    actions = _normalize_actions(actions_raw)
    conclusion = str(raw.get("final_conclusion") or raw.get("conclusion") or "").strip()

    if not overview:
        overview = "Summary generated from the provided meeting transcript."
    if not conclusion:
        conclusion = overview

    result = {
        "overview": overview,
        "discussion_points": discussion,
        "decisions": decisions,
        "action_items": _format_action_display(actions),
        "action_items_structured": actions,
        "final_conclusion": conclusion,
        "raw_json": raw,
    }

    logger.info("Summary generated: %s discussion points, %s actions", len(discussion), len(actions))
    return result
