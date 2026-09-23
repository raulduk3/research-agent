from research_agent.reader.latex import (
    MAX_INPUT_DEPTH,
    brace_group,
    hidden_by_comment,
    resolve_submission,
)


def test_brace_group_skips_nested_and_escaped_braces() -> None:
    text = r"{a {b} \} c}tail"
    assert brace_group(text, 0) == text.index("tail")
    assert brace_group("{open", 0) is None
    assert brace_group("x{}", 0) is None


def test_hidden_by_comment_covers_line_comments_and_blocks() -> None:
    text = (
        "kept 50\\% % gone\n"
        "break\\\\% after a line break\n"
        "% \\iffalse inside a comment starts nothing\n"
        "visible\n"
        "\\begin{comment}\nhidden env\n\\end{comment}\n"
        "\\iffalse hidden if \\fi shown\n"
    )
    hidden = hidden_by_comment(text)
    assert not hidden(text.index("kept"))
    assert not hidden(text.index("50"))
    assert hidden(text.index("gone"))
    assert not hidden(text.index("break"))
    assert hidden(text.index("after a line break"))
    assert not hidden(text.index("visible"))
    assert hidden(text.index("hidden env"))
    assert hidden(text.index("hidden if"))
    assert not hidden(text.index("shown"))


def test_resolve_submission_inlines_input_and_include_from_the_root() -> None:
    files = {
        "./main.tex": (
            "\\documentclass{revtex4}\n\\begin{document}\n"
            "\\input{sections/intro}\n\\include{sections/method.tex}\n"
            "\\input sections/end\n\\end{document}\n"
        ),
        "sections/intro.tex": "\\section{Introduction}\nIntro text.\n",
        "sections/method.tex": "\\section{Method}\nMethod text.\n",
        "sections/end.tex": "\\section{Conclusion}\nDone.\n",
        # Larger than the root, so the old largest-member rule picked it.
        "appendix-notes.tex": "notes " * 200,
    }
    resolved = resolve_submission(files)
    assert resolved is not None
    assert resolved.startswith("\\documentclass{revtex4}")
    for body in ("Intro text.", "Method text.", "Done."):
        assert body in resolved
    assert "\\input" not in resolved and "\\include{" not in resolved
    assert "notes" not in resolved


def test_resolve_submission_leaves_unresolvable_and_unsafe_references() -> None:
    files = {
        "main.tex": (
            "\\documentclass{article}\n"
            "% \\input{commented}\n"
            "\\input{../outside}\n\\input{/etc/passwd}\n\\input{figure.pgf}\n"
            "\\input{missing}\n\\includegraphics{plot}\n"
        ),
        "commented.tex": "SHOULD NOT APPEAR",
        "figure.pgf": "PGF CODE",
    }
    resolved = resolve_submission(files)
    assert resolved == files["main.tex"]


def test_resolve_submission_stops_cycles_and_depth() -> None:
    chain = {f"f{n}.tex": f"level {n}\n\\input{{f{n + 1}}}\n" for n in range(12)}
    chain["f0.tex"] = "\\documentclass{article}\n" + chain["f0.tex"]
    resolved = resolve_submission(chain)
    assert resolved is not None
    assert f"level {MAX_INPUT_DEPTH}\n" in resolved
    assert f"level {MAX_INPUT_DEPTH + 1}\n" not in resolved
    assert f"\\input{{f{MAX_INPUT_DEPTH + 1}}}" in resolved

    cycle = {
        "a.tex": "\\documentclass{article}\nA\\input{b}",
        "b.tex": "B\\input{a}",
    }
    assert resolve_submission(cycle) == "\\documentclass{article}\nAB\\input{a}"


def test_resolve_submission_prefers_the_root_that_resolves_longest() -> None:
    files = {
        "figure.tex": "\\documentclass{standalone}\n\\begin{document}x\\end{document}",
        "paper.tex": "\\documentclass{article}\n\\input{body}",
        "body.tex": "\\section{Results}\n" + "body text " * 50,
    }
    resolved = resolve_submission(files)
    assert resolved is not None and resolved.startswith("\\documentclass{article}")
    assert "body text" in resolved


def test_resolve_submission_without_a_root_marker_takes_the_longest_file() -> None:
    files = {"small.tex": "\\section{A}", "main.tex": "\\section{Main}" * 5}
    assert resolve_submission(files) == "\\section{Main}" * 5
    assert resolve_submission({}) is None
