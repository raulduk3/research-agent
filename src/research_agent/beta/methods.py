"""Versioned research methods, adapted to the swarm's stored-paper tools."""

from __future__ import annotations

import re

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

VERSION = 1


@dataclass(frozen=True)
class DomainMethods:
    tools: str
    label: str
    evidence: str
    questions: tuple[str, str, str]
    sources: tuple[tuple[str, str], ...]


CATALOG = {
    "cs": DomainMethods(
        "Use paper_text for data splits, evaluation settings and ablations;"
        " related_papers for fair baseline comparisons; cited_paper_text for the"
        " reused baseline method; capture_note for reproduction gaps and a"
        " component-control experiment.",
        "Computer science: empirical evaluation and reproducibility",
        "For empirical claims, compare data splits, metrics, baseline tuning budgets,"
        " random seeds and reported variability. Separate ablation evidence for a"
        " component from a whole-system gain. For theoretical claims, inspect the"
        " theorem's assumptions instead of demanding experiments.",
        (
            "Trace the main gain to its experiment or theorem and check its scope.",
            "Check whether stronger baselines, adaptive overfitting or missing"
            " component controls could explain the gain.",
            "Propose a reproducible baseline comparison or component ablation with"
            " a fixed evaluation budget and explicit success metric.",
        ),
        (
            (
                "Pineau et al., JMLR 2021, sections 2 and 5",
                "https://jmlr.org/papers/volume22/20-303/20-303.pdf",
            ),
        ),
    ),
    "quant": DomainMethods(
        "Use paper_text for observables, noise and resource estimates;"
        " related_papers for classical simulator comparisons; cited_paper_text"
        " for the validation method; capture_note for certification assumptions"
        " and extrapolation limits.",
        "Quantum research: certification and computational resources",
        "Distinguish simulated from measured performance and a task-specific"
        " advantage from a general claim. Inspect verification, error sources,"
        " system size and classical comparison; track how evidence and costs"
        " change with scale. Do not treat small-system agreement as certification"
        " of every larger instance.",
        (
            "Locate the observable and validation evidence supporting the quantum claim.",
            "Challenge the certification assumptions, noise model and classical"
            " comparison at the claimed scale.",
            "Propose a tractable classical benchmark or cross-check and identify"
            " the resource and error limits of extending it.",
        ),
        (
            (
                "Daley et al., Nature 2022, practical quantum advantage",
                "https://www.nature.com/articles/s41586-022-04940-6",
            ),
        ),
    ),
    "bio": DomainMethods(
        "Use paper_text for experimental units, perturbations and controls;"
        " cited_paper_text for a referenced assay or control method;"
        " related_papers for contrasting biological evidence; capture_note for"
        " mechanistic alternatives and a discriminating perturbation.",
        "Biology: mechanisms and controlled experimental design",
        "Separate association from mechanistic support. Identify the experimental"
        " unit, independent biological replicates, controls, allocation, blinding"
        " and relevant biological variables. Inspect whether the intervention"
        " and comparison rule out alternative explanations; flag missing design"
        " information rather than inventing it.",
        (
            "Trace a mechanism claim to the intervention and measured biological outcome.",
            "Check confounding, pseudoreplication, control adequacy and bias in"
            " allocation or measurement.",
            "Propose a controlled perturbation and comparison with independent"
            " replicates and a defined outcome.",
        ),
        (
            (
                "NIH, principles for reporting preclinical research",
                "https://www.grants.nih.gov/policy-and-compliance/policy-topics/"
                "reproducibility/principles-guidelines-reporting-preclinical-research",
            ),
        ),
    ),
    "general": DomainMethods(
        "Use paper_text for assumptions, objectives, convergence or update"
        " rules; cited_paper_text for the statistical or solver method;"
        " related_papers for matched benchmarks or model comparisons; capture_note"
        " for an uncertainty, convergence or sensitivity check.",
        "General research: statistical inference, optimization and simulation",
        "Interpret effect size, uncertainty and model assumptions together; a"
        " significance threshold alone does not establish importance. For"
        " optimization inspect feasibility, optimality conditions and stopping"
        " criteria. For simulations inspect purpose, state variables, update"
        " rules, initialization and fitness for purpose.",
        (
            "Identify the estimand, objective or model purpose and its supporting evidence.",
            "Check selective reporting, model assumptions, claimed optimality and"
            " whether simulated patterns support the stated purpose.",
            "Propose an uncertainty analysis, a feasible benchmark with a stopping"
            " criterion, or a reproducible simulation comparison as appropriate.",
        ),
        (
            (
                "ASA, 2016 p-value statement, six principles",
                "https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf",
            ),
            (
                "Boyd and Vandenberghe, Convex Optimization, chapters 5 and 9",
                "https://web.stanford.edu/~boyd/cvxbook/",
            ),
            ("Grimm et al., ODD protocol, 2020", "https://www.jasss.org/23/2/7.html"),
        ),
    ),
}


def methods_profile(
    island_id: str, focus: str, categories: Sequence[str] = ()
) -> dict[str, Any]:
    """Keep provenance in genome data and research instructions in their own field."""
    methods = CATALOG.get(island_id, CATALOG["general"])
    fallback = (
        " Apply these general methods only where they fit the stated focus and categories."
        if island_id not in CATALOG
        else ""
    )
    lines = [
        f"Research domain: {methods.label}. Focus: {focus}.",
        f"Categories: {', '.join(categories) or 'unspecified'}.{fallback}",
        methods.evidence,
        "For evidence reading: " + methods.questions[0],
        "For skeptical reading: " + methods.questions[1],
        "For reusable contributions: " + methods.questions[2],
        methods.tools,
        "These tools retrieve stored evidence; they cannot execute experiments."
        " Respect allowed_tools and cost_state limits. Consult feedback_context"
        " for group context, not scientific proof, then submit_reading. If only"
        " metadata or an abstract is available, mark checks as unresolved and"
        " bound the conclusion.",
    ]
    return {
        "version": VERSION,
        "domain": island_id if island_id in CATALOG else "general",
        "specialist": island_id in CATALOG,
        "instructions": "\n".join(lines),
        "sources": [{"title": title, "url": url} for title, url in methods.sources],
    }


def island_methods(island: Mapping[str, Any]) -> dict[str, Any]:
    return methods_profile(
        str(island["id"]), str(island["focus"]), island["categories"]
    )


_INSTRUCTION_BREAK = re.compile(
    r"[.!?][\"'”’)\]]*(?P<sentence>\s+)|(?P<paragraph>\n[ \t]*\n+)"
    r"|(?P<bullet>\n)(?=\s*(?:[-*•]|\d+[.)])\s+)"
)
_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "et al.",
    "etc.",
    "vs.",
    "fig.",
    "eq.",
    "dr.",
    "prof.",
)
_GENERATED_EMPHASIS = re.compile(
    r"^(?:Additional reading emphasis|Emphasis|Reading strategy):\s*"
)


_PROTECTED_LITERAL = re.compile(
    r"```[\s\S]*?(?:```|$)|\$\$[\s\S]*?\$\$|`[^`]*`"
    r'|(?<!\\)\$(?=\S)[^\n$]*\S(?<!\\)\$|"(?:\\.|[^"\\])*"|“[^”]*”|‘[^’]*’'
    r"|(?<!\w)'(?:\\.|[^'\\])*'(?!\w)"
)


def instruction_key(text: str) -> tuple[tuple[str, str], ...]:
    """Normalize prose whitespace while retaining literal bytes for comparison."""
    parts: list[tuple[str, str]] = []
    start = 0
    for match in _PROTECTED_LITERAL.finditer(text):
        parts.append(("prose", " ".join(text[start : match.start()].split())))
        parts.append(("literal", match.group()))
        start = match.end()
    parts.append(("prose", " ".join(text[start:].split())))
    return tuple(parts)


def unique_instructions(text: str) -> str:
    """Keep the first copy of exact instruction units, including wrapped text."""
    protected = [match.span() for match in _PROTECTED_LITERAL.finditer(text)]
    duplicate_lines = [
        match.span()
        for match in re.finditer(r"(?m)^([^\n]+)\n(?=\1(?:\n|$))", text)
        if not any(
            first < match.end() and match.start() < last for first, last in protected
        )
    ]
    if duplicate_lines:
        for first, last in reversed(duplicate_lines):
            text = text[:first] + text[last:]
        return unique_instructions(text)
    units: list[tuple[str, str]] = []
    start = 0
    for match in _INSTRUCTION_BREAK.finditer(text):
        group = match.lastgroup
        assert group is not None
        boundary = match.start(group)
        if any(first <= boundary < last for first, last in protected):
            continue
        unit = text[start:boundary]
        if group == "sentence" and (
            unit.lower().endswith(_ABBREVIATIONS)
            or re.search(r"\b(?:[A-Za-z]\.){2,}$", unit)
        ):
            continue
        units.append((unit, match.group(group)))
        start = match.end()
    units.append((text[start:], ""))
    seen: set[tuple[tuple[str, str], ...]] = set()
    kept: list[tuple[str, str]] = []
    for unit, separator in units:
        unit = unit.strip()
        prefix = _GENERATED_EMPHASIS.match(unit)
        key = unit
        while _GENERATED_EMPHASIS.match(key):
            key = _GENERATED_EMPHASIS.sub("", key)
        if prefix:
            unit = prefix.group() + key
        key = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", key)
        comparison = instruction_key(key)
        if not key.strip() or comparison in seen:
            if kept and separator.count("\n") > kept[-1][1].count("\n"):
                kept[-1] = (kept[-1][0], separator)
            continue
        seen.add(comparison)
        kept.append((unit, separator))
    return "".join(unit + separator for unit, separator in kept).strip()


def mix_methods(profiles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Blend complete parent instructions and sources without silently truncating."""
    usable = [profile for profile in profiles if profile]
    if not usable:
        return {}
    domains = {profile["domain"] for profile in usable}
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for profile in usable:
        for source in profile["sources"]:
            if source["url"] not in seen:
                seen.add(source["url"])
                sources.append(dict(source))
    return {
        "version": max(profile["version"] for profile in usable),
        "domain": usable[0]["domain"] if len(domains) == 1 else "mixed",
        "specialist": len(domains) == 1
        and all(profile["specialist"] for profile in usable),
        "instructions": unique_instructions(
            "\n\n".join(profile["instructions"] for profile in usable)
        ),
        "sources": sources,
    }
