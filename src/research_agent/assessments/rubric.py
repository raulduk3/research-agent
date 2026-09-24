"""The versioned eight-question Jev rubric (RD-16, TDD-4.1.54).

Each RD-16 row becomes one question in its primitive: a `choice` carries its
full category criteria, a `score` its ordered criteria, one per scale point,
and a `noul` only its instructions, answered by the probability of yes. All
eight inspect the same supplied text and none is gated on another's answer;
every question asks what the paper reports, and novelty only as the paper
claims it. The rubric lives outside the mutable genome: only an approved
body is admitted under its version, only the operator role may admit one,
and a changed body under a reused version is refused.

`jev-rubric-v2` is the launch rubric (#267). `jev-rubric-v1`, eight
`choice` questions, keeps its body and hash so its stored assessments still
load and render.

The examples are development-only rubric artifacts, one positive and one
boundary example per category of a `choice` question. They are illustrative
sentences with no `reference_hash`, not drawn from any corpus paper, and are
not sent to the provider; they are hashed with the rubric so that replacing
them with development-set examples before the smoke test is a new version.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.assessments import (
    FIELD_CATEGORIES,
    FIELD_IDS,
    V1_FIELD_IDS,
    V1_RUBRIC_VERSION,
    V2_RUBRIC_VERSION,
    JevRubric,
    NoulQuestion,
    RubricExample,
    RubricQuestion,
    ScoreQuestion,
)

__all__ = [
    "LAUNCH_RUBRIC_VERSION",
    "RUBRIC_ADMITTING_ROLE",
    "RubricRejected",
    "Rubric",
]

LAUNCH_RUBRIC_VERSION = V2_RUBRIC_VERSION
_LAUNCH_CREATED_AT = "2026-09-23T00:00:00.000000Z"

#: The one role that may admit a rubric; an agent, the Jev provider or any
#: run role cannot (RD-16, AG-35).
RUBRIC_ADMITTING_ROLE = "operator"

_SHARED = "Judge only the supplied paper text; do not use outside knowledge."

# field -> (question, ((category, criterion, positive, boundary), ...))
# Each example is (text, explanation).
_Example = tuple[str, str]
_Row = tuple[str, str, _Example, _Example]

_NOT_APPLICABLE = "The question has no meaningful target in this paper."
_INSUFFICIENT = (
    "Missing content or ambiguity in the supplied text prevents classification."
)
_TRUNCATED = (
    "The supplied text is only a title and a partial introduction.",
    "Missing content, not a finding about the paper.",
)
_TRUNCATED_BOUNDARY = (
    "The results section is present but its tables were not extracted.",
    "The key evidence may exist but cannot be read; choose this over not reported.",
)

_RUBRIC: Mapping[str, tuple[str, tuple[_Row, ...]]] = {
    "primary_contribution": (
        "What is the paper's primary contribution? Mixed/other applies when no "
        "single primary contribution dominates.",
        (
            (
                "method_system",
                "A new method, algorithm, model architecture or system.",
                (
                    "We propose a new attention variant and evaluate it.",
                    "The new method is the core claim.",
                ),
                (
                    "We release a system and a small benchmark to test it.",
                    "The benchmark serves the system; the system dominates.",
                ),
            ),
            (
                "dataset_resource",
                "A new dataset, corpus, annotation set or other reusable resource.",
                (
                    "We present a corpus of 40k annotated clinical notes.",
                    "The resource is the contribution.",
                ),
                (
                    "We collect a dataset solely to train our proposed model.",
                    "Boundary: if the model dominates, choose method/system.",
                ),
            ),
            (
                "benchmark_evaluation_method",
                "A new benchmark, evaluation protocol or metric.",
                (
                    "We introduce a benchmark suite and evaluate twelve models on it.",
                    "The evaluation instrument is the contribution.",
                ),
                (
                    "We compare existing models on existing benchmarks.",
                    "Boundary: no new instrument; this is empirical analysis.",
                ),
            ),
            (
                "theoretical_result",
                "A theorem, bound, proof or formal analysis.",
                (
                    "We prove a tight lower bound for sample complexity.",
                    "The formal result is the contribution.",
                ),
                (
                    "We derive an update rule and then test it experimentally.",
                    "Boundary: if the method dominates, choose method/system.",
                ),
            ),
            (
                "empirical_analysis_replication",
                "An empirical study, analysis or replication of existing work.",
                (
                    "We replicate five published results and report which hold.",
                    "Analysis of existing work is the contribution.",
                ),
                (
                    "We study scaling behavior with a new training trick.",
                    "Boundary: if the trick dominates, choose method/system.",
                ),
            ),
            (
                "synthesis_survey",
                "A survey, review, tutorial or position synthesis of prior work.",
                (
                    "We survey 200 papers on retrieval-augmented generation.",
                    "Synthesis of prior work is the contribution.",
                ),
                (
                    "We review prior work at length before proposing a method.",
                    "Boundary: a long related-work section is not a survey.",
                ),
            ),
            (
                "mixed_other",
                "Several contributions of comparable weight, or a kind not listed.",
                (
                    "We release a dataset, a model and a proof, each a stated main result.",
                    "No single contribution dominates.",
                ),
                (
                    "A method paper that also releases its training data.",
                    "Boundary: the method dominates, so this is not mixed.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "comparative_evaluation": (
        "Does the paper report a comparison to an alternative or baseline "
        "addressing a contribution? Presence does not establish fairness or "
        "superiority.",
        (
            (
                "reported",
                "A comparison to an alternative or baseline addressing a contribution is reported.",
                (
                    "Table 2 compares our model with three prior methods.",
                    "A reported comparison.",
                ),
                (
                    "We compare against a baseline we implemented ourselves.",
                    "Still a comparison; fairness is not judged.",
                ),
            ),
            (
                "explicitly_absent",
                "The paper explicitly states that no such comparison was made.",
                (
                    "No baseline exists for this task, so we report absolute scores only.",
                    "An explicit statement of absence.",
                ),
                (
                    "Comparison is left to future work.",
                    "Explicitly absent, not merely unmentioned.",
                ),
            ),
            (
                "not_reported",
                "No qualifying statement about a comparison appears in the supplied text.",
                (
                    "Results report only the proposed method's accuracy.",
                    "No comparison and no statement about one.",
                ),
                (
                    "Prior methods are discussed in related work but not evaluated.",
                    "Discussion is not a reported comparison.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                (
                    "A pure proof with no empirical component.",
                    "No evaluation to compare.",
                ),
                (
                    "A survey with a table summarizing others' reported numbers.",
                    "Boundary: a survey's summary is not its own comparison.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "ablation_component_analysis": (
        "Does the paper report isolating a component or design choice's effect? "
        "Presence does not establish causal identification.",
        (
            (
                "reported",
                "An analysis isolating a component or design choice's effect is reported.",
                (
                    "Removing the gating layer drops accuracy by 3 points.",
                    "A reported ablation.",
                ),
                (
                    "We vary one hyperparameter and plot the effect.",
                    "Isolates one design choice; counts.",
                ),
            ),
            (
                "explicitly_absent",
                "The paper explicitly states no such analysis was made.",
                (
                    "Due to compute limits we did not run ablations.",
                    "An explicit statement of absence.",
                ),
                (
                    "Ablations are deferred to a follow-up paper.",
                    "Explicitly absent here.",
                ),
            ),
            (
                "not_reported",
                "No qualifying statement about component analysis appears.",
                (
                    "Only the full model is evaluated.",
                    "No ablation and no statement about one.",
                ),
                (
                    "Two different models are compared end to end.",
                    "A comparison, not an isolated component.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                (
                    "A dataset paper with no model of its own.",
                    "No component to isolate.",
                ),
                (
                    "A survey that discusses others' ablations.",
                    "Boundary: reporting others' ablations is not its own.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "uncertainty_reporting": (
        "Does the paper report variation across repeated measurements, an "
        "interval or a statistical test for an empirical result? Presence does "
        "not establish statistical validity.",
        (
            (
                "reported",
                "Variation across repeats, an interval or a statistical test is reported for an empirical result.",
                (
                    "Mean and standard deviation over five seeds.",
                    "Variation across repeated runs.",
                ),
                (
                    "A single p-value for the main comparison.",
                    "A statistical test counts; validity is not judged.",
                ),
            ),
            (
                "explicitly_absent",
                "The paper explicitly states that no such reporting was done.",
                (
                    "Each configuration was run once due to cost.",
                    "An explicit statement of absence.",
                ),
                ("We do not report error bars.", "Explicitly absent."),
            ),
            (
                "not_reported",
                "No qualifying statement appears for its empirical results.",
                (
                    "Point accuracies with no spread or test.",
                    "No uncertainty and no statement about it.",
                ),
                (
                    "Results are 'consistent across runs' with no numbers.",
                    "An unquantified claim is not reporting.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                (
                    "A purely theoretical paper with no empirical results.",
                    "No empirical result to qualify.",
                ),
                (
                    "A theory paper with one illustrative plot.",
                    "Boundary: an illustration is not a reported result.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "theoretical_support": (
        "Does the paper supply a proof or derivation supporting a contribution? "
        "This does not verify a proof.",
        (
            (
                "proof_or_derivation_supplied",
                "A proof or derivation supporting a contribution is supplied in the text or appendices.",
                ("Appendix B proves Theorem 1.", "A supplied proof."),
                (
                    "A proof sketch in the main text, full proof omitted.",
                    "A sketch is supplied support; correctness is not judged.",
                ),
            ),
            (
                "support_elsewhere",
                "The paper states that the support appears elsewhere.",
                (
                    "The proof appears in our companion paper.",
                    "Support stated to be elsewhere.",
                ),
                (
                    "Follows from a cited textbook result.",
                    "Pointed elsewhere, not supplied here.",
                ),
            ),
            (
                "not_reported",
                "No qualifying statement about theoretical support appears.",
                (
                    "The method is motivated by intuition only.",
                    "No proof and no pointer to one.",
                ),
                (
                    "Equations define the model but prove nothing about it.",
                    "Definitions are not a derivation of a claim.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                (
                    "A dataset release with descriptive statistics only.",
                    "No claim that theory would support.",
                ),
                (
                    "An empirical replication of a theoretical prediction.",
                    "Boundary: tests theory, supplies none.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "evaluation_beyond_main_setting": (
        "Does the paper report testing a contribution in another dataset, "
        "domain, environment or operating condition? This does not establish "
        "generalization.",
        (
            (
                "reported",
                "Testing in another dataset, domain, environment or operating condition is reported.",
                (
                    "We also evaluate on two out-of-domain test sets.",
                    "Reported beyond the main setting.",
                ),
                (
                    "We test at a different input resolution.",
                    "A different operating condition counts.",
                ),
            ),
            (
                "explicitly_limited_to_main_setting",
                "The paper explicitly limits its evaluation to the main setting.",
                ("We evaluate only on English news text.", "Explicitly limited."),
                (
                    "Other domains are out of scope for this work.",
                    "Explicit limitation of the setting.",
                ),
            ),
            (
                "not_reported",
                "No qualifying statement about other settings appears.",
                (
                    "One dataset, no discussion of others.",
                    "No other setting and no statement about one.",
                ),
                (
                    "Train and test splits of the same dataset.",
                    "A held-out split is still the main setting.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                ("A proof with no evaluation.", "No evaluation to extend."),
                (
                    "A survey comparing settings across others' papers.",
                    "Boundary: not its own contribution's test.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "artifact_availability_statement": (
        "Does the paper claim an implementation, data or model artifact is "
        "available? Available means at least one artifact is claimed "
        "available; future-only means none is claimed available and at least "
        "one is promised. No external availability is verified.",
        (
            (
                "claimed_available",
                "At least one implementation, data or model artifact is claimed available.",
                (
                    "Code is available at a public repository.",
                    "A claimed-available artifact.",
                ),
                (
                    "Data is available; code will be released later.",
                    "One artifact available is enough.",
                ),
            ),
            (
                "future_only",
                "None is claimed available and at least one is promised.",
                ("Code will be released upon acceptance.", "A promise only."),
                ("We plan to release the model weights.", "Promised, none available."),
            ),
            (
                "explicitly_unavailable",
                "The paper states the artifacts are not available.",
                (
                    "The data cannot be shared for privacy reasons.",
                    "Explicitly unavailable.",
                ),
                ("The code is proprietary.", "Explicitly unavailable."),
            ),
            (
                "not_reported",
                "No qualifying statement about artifact availability appears.",
                ("No mention of code, data or model release.", "No statement."),
                (
                    "Uses a public dataset but says nothing of its own code.",
                    "Using public data is not an availability claim.",
                ),
            ),
            (
                "not_applicable",
                _NOT_APPLICABLE,
                (
                    "A position paper with no implementation or data.",
                    "No artifact exists to release.",
                ),
                (
                    "A proof accompanied by a symbolic verification script.",
                    "Boundary: the script is an artifact; this is applicable.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
    "limitations_disclosure": (
        "Does the paper state a concrete assumption, failure case or scope "
        "restriction relevant to the contribution? A limitations heading "
        "alone is not a concrete disclosure. This does not measure "
        "completeness or severity.",
        (
            (
                "concrete_limitation",
                "A concrete assumption, failure case or scope restriction relevant to the contribution is stated.",
                (
                    "The method fails on inputs longer than 4k tokens.",
                    "A concrete failure case.",
                ),
                (
                    "We assume i.i.d. samples, which excludes time series.",
                    "A concrete assumption and scope.",
                ),
            ),
            (
                "generic_caveats_only",
                "Only generic caveats appear.",
                ("Like all models, ours may make mistakes.", "Generic caveat."),
                (
                    "A 'Limitations' heading saying more work is needed.",
                    "A heading alone is not concrete.",
                ),
            ),
            (
                "not_reported",
                "No qualifying statement about limitations appears.",
                ("No limitation or caveat is stated.", "No statement."),
                (
                    "Future work lists extensions without naming a weakness.",
                    "Extensions are not a limitation.",
                ),
            ),
            (
                "insufficient_information",
                _INSUFFICIENT,
                _TRUNCATED,
                _TRUNCATED_BOUNDARY,
            ),
        ),
    ),
}


# The v2 rows of decision #267. field -> (question, criteria from point 0).
_SCORES: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "evaluation_rigor": (
        "How thoroughly does the paper report evaluating its main "
        "contribution? Choose the highest point whose description the "
        "supplied text meets.",
        (
            "No evaluation of the contribution is reported.",
            "An evaluation in one setting, with no baseline or alternative compared.",
            "A comparison to at least one baseline or alternative is reported.",
            "Baselines and an ablation isolating a component or design choice are reported.",
            "Baselines and ablations are reported, with variation over seeds or runs, "
            "intervals or a statistical test.",
        ),
    ),
    "limitations_candor": (
        "How concretely does the paper state the limits of its contribution? "
        "A limitations heading alone is generic.",
        (
            "No limitation or caveat is stated.",
            "Only generic caveats are stated.",
            "A concrete assumption, failure case or scope restriction relevant "
            "to the contribution is stated.",
            "Concrete limitations are stated and failure cases are shown.",
        ),
    ),
    "novelty_as_claimed": (
        "What kind of novelty does the paper claim for its contribution? "
        "Record the paper's own claim; do not judge whether it holds.",
        (
            "An incremental improvement or extension of existing work.",
            "A new method for an existing problem.",
            "A new problem, task or capability.",
            "A new paradigm for its field.",
        ),
    ),
}

# field -> the statement whose probability of being true the answer gives.
_NOULS: Mapping[str, str] = {
    "claims_supported_by_evidence": (
        "The headline claims are supported by the evidence the paper reports."
    ),
    "reproducible_from_materials": (
        "An independent group could reproduce the main result from the "
        "materials the paper says it releases."
    ),
    "generalizes_beyond_main_setting": (
        "The results are shown to hold beyond the main setting."
    ),
    "open_problems_stated": (
        "The paper names questions or gaps it leaves unsettled, in its "
        "limitations, future work or open problems."
    ),
}


class RubricRejected(Exception):
    """A rubric was refused: altered under a reused version, or not the operator's."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"rubric rejected: {reason}")
        self.reason = reason


def _choice(field_id: str) -> RubricQuestion:
    question, rows = _RUBRIC[field_id]
    examples = tuple(
        RubricExample(category, kind, text, explanation, None)
        for category, _, positive, boundary in rows
        for kind, (text, explanation) in (
            ("positive", positive),
            ("boundary", boundary),
        )
    )
    return RubricQuestion(
        field_id=field_id,
        question=f"{question} {_SHARED}",
        category_ids=tuple(row[0] for row in rows),
        category_criteria=tuple(row[1] for row in rows),
        examples=examples,
    )


def _v1_record() -> JevRubric:
    questions = tuple(_choice(field_id) for field_id in V1_FIELD_IDS)
    return JevRubric(V1_RUBRIC_VERSION, questions, _LAUNCH_CREATED_AT)


def _v2_record() -> JevRubric:
    questions: list[RubricQuestion | ScoreQuestion | NoulQuestion] = []
    for field_id in FIELD_IDS:
        if field_id in FIELD_CATEGORIES:
            questions.append(_choice(field_id))
        elif field_id in _SCORES:
            question, criteria = _SCORES[field_id]
            questions.append(ScoreQuestion(field_id, f"{question} {_SHARED}", criteria))
        else:
            statement = _NOULS[field_id]
            questions.append(
                NoulQuestion(
                    field_id,
                    "Answer yes if the supplied paper's own text supports this "
                    f"statement: {statement} {_SHARED}",
                    statement,
                )
            )
    return JevRubric(V2_RUBRIC_VERSION, tuple(questions), _LAUNCH_CREATED_AT)


@dataclass(frozen=True, slots=True)
class Rubric:
    """An admitted, hashed rubric and the eight questions it sends."""

    record: JevRubric

    @property
    def version(self) -> str:
        return self.record.version

    @property
    def rubric_hash(self) -> str:
        return self.record.rubric_hash

    @classmethod
    def launch(cls) -> "Rubric":
        return cls(_v2_record())

    @classmethod
    def v1(cls) -> "Rubric":
        """The first rubric, kept so its stored assessments still load."""

        return cls(_v1_record())

    @classmethod
    def admit(
        cls,
        candidate: JevRubric,
        *,
        writer_role: str,
        approved: Mapping[str, str],
    ) -> "Rubric":
        """Admit `candidate` only from the operator and only as its approved body.

        `approved` maps each rubric version to the hash approved for it. A
        version already approved with a different body is an unversioned
        alteration and is refused, as is any rubric an agent (or any role
        but the operator) supplies.
        """

        if writer_role != RUBRIC_ADMITTING_ROLE:
            raise RubricRejected("rubric_mutation_denied")
        expected = approved.get(candidate.version)
        if expected is None:
            raise RubricRejected("unapproved_version")
        if expected != candidate.rubric_hash:
            raise RubricRejected("altered_rubric_version")
        return cls(candidate)

    def request_questions(self) -> dict[str, dict[str, Any]]:
        """The eight wire questions, one per field, in the provider's shapes.

        A `choice` maps each option to its criterion, a `score` lists its
        criteria in scale order and a `noul` carries instructions only.
        Every question inspects the same supplied state; none is gated on
        another's answer. Examples are development artifacts and are not sent.
        """

        questions: dict[str, dict[str, Any]] = {}
        for question in self.record.questions:
            if isinstance(question, RubricQuestion):
                questions[question.field_id] = {
                    "type": "choice",
                    "instructions": question.question,
                    "criteria": dict(
                        zip(
                            question.category_ids,
                            question.category_criteria,
                            strict=True,
                        )
                    ),
                }
            elif isinstance(question, ScoreQuestion):
                questions[question.field_id] = {
                    "type": "score",
                    "instructions": question.question,
                    "criteria": list(question.criteria),
                }
            else:
                questions[question.field_id] = {
                    "type": "noul",
                    "instructions": question.question,
                }
        return questions

    def categories(self, field_id: str) -> tuple[str, ...]:
        return FIELD_CATEGORIES[field_id]
