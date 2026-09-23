"""Seeded evolution: cycle-gated selection, mutation, migration and archive.

This package holds the population-side mechanics of Appendix A's seeded
evolution (AG-06, AG-19 to AG-21, AG-35, AG-37, FT-27): pure functions of an
explicit population snapshot, never a hidden clock, model call or database
read, following the same boundary ``orchestration/scheduler.py`` draws for
the coverage sample -- a caller backs the storage-reading cycle guard
(``research_agent.orchestration.selection.cycle_guard``) and the FT-14 select
stage (``research_agent.orchestration.selection.select_population``) with
real persistence once that integration exists; what is built here is the
decision each of those requirements makes from its inputs. The one
exception is ``population.py``, the population store those decisions are
read from and written through (#177).
"""

from __future__ import annotations
