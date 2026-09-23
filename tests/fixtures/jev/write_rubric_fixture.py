"""Regenerate the approved rubric artifacts after an intended, versioned change.

Run `uv run python tests/fixtures/jev/write_rubric_fixture.py`. A change to
a rubric body must come with a new rubric version; the rubric test fails
until these artifacts are regenerated and reviewed.
"""

import json
from pathlib import Path

from research_agent.assessments.rubric import Rubric

for rubric, name in (
    (Rubric.v1(), "rubric-v1-questions.json"),
    (Rubric.launch(), "rubric-v2-questions.json"),
):
    document = {
        "version": rubric.version,
        "rubric_hash": rubric.rubric_hash,
        "questions": rubric.request_questions(),
    }
    Path(__file__).with_name(name).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
