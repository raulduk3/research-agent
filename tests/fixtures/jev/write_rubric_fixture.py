"""Regenerate the approved rubric artifact after an intended, versioned change.

Run `uv run python tests/fixtures/jev/write_rubric_fixture.py`. A change to
the rubric body must come with a new rubric version; the rubric test fails
until this artifact is regenerated and reviewed.
"""

import json
from pathlib import Path

from research_agent.assessments.rubric import Rubric

rubric = Rubric.launch()
document = {
    "version": rubric.version,
    "rubric_hash": rubric.rubric_hash,
    "questions": rubric.choice_questions(),
}
Path(__file__).with_name("rubric-v1-questions.json").write_text(
    json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
