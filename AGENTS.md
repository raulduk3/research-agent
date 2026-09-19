# Contributor instructions

These instructions apply to every contributor, human or automated. `CONTRIBUTING.md` is the working policy they summarize; where the two differ, `CONTRIBUTING.md` wins.

## Build and test

None yet. The repository holds the policy files and the specification under `docs/spec/`. The implementation language and its toolchain are an open decision; the pull request that carries that decision adds the commands here and the same commands to CI.

Until then a change is checked by review against this file, `CONTRIBUTING.md` and, for a specification change, the conventions at the top of `docs/spec/SDD.md` and `docs/spec/TDD.md`.

## Change rules

- One change, one branch cut from `develop`, one pull request to `develop`. Branch name `type/short-description`. No stacked pull requests: a change that depends on another waits for it to merge, then cuts from `develop`.
- Make the smallest coherent change that completes the request.
- Code, tests, and the documentation the change affects ship in the same pull request.
- Read the code you are changing and its tests before editing.
- Prefer editing an existing owner over adding a parallel one. No speculative abstractions.
- Tests detect a concrete prohibited alternative. Do not mock away the owner under test.
- Stage only the files that belong to the change. Preserve unrelated uncommitted work.
- The pull request description follows `.github/pull_request_template.md` and is the record of the change.

## Commit format

`type(scope): summary`. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`. Subject under 72 characters, imperative, no trailing period. The body explains why. `Closes #N` links the issue. `!` after the type, or a `BREAKING CHANGE:` footer, marks a major change.

Commits and changed source lines describe the software, not the process that produced it: no names of people, tools, models, sessions or run identifiers, and no work-tracking labels. Reference issues and pull requests by number. Review enforces this until an automated check exists.

Co-author trailers are NOT allowed.

## Who may merge

An automated contributor opens its own pull request and merges it once the change is complete and its own review has run. It does not wait for a human. Speed is worth more here than a second opinion, because everything this repository holds is text under version control and a bad merge is one revert away.

What that costs, stated so nobody is surprised by it: a wrong requirement can reach `develop` unread. The defence is that every change is small, cited to a decision, and recorded in the amendment ledger, so it can be found and reverted. Use `git revert`, not history rewriting.

`main` is different. It carries releases and is the owner's alone.

## Never

- Push to `main`, or tag a release.
- Deploy, publish, rotate a credential or restart a service without the owner's explicit instruction in the current session.
- Amend, rebase, reset or force-push a commit that has been pushed for review.
- Touch another branch's worktree: never reset, clean or delete it.
- Put a credential in source, documentation, prompts, commands, fixtures, logs or commit messages.

## Contracts

- `README.md` says what the software is and how to run it.
- `docs/` holds the contracts; `docs/decisions/` holds accepted decisions as records.
- GitHub issues hold every open decision and known deviation, cited by number.

If code and contract disagree, say so with evidence and fix the one that is wrong. Do not improvise a local workaround.

## Scope freezes

None. A new feature needs the owner's decision on a GitHub issue before a branch is cut.

## Precedence

If a prompt, tool or automation conflicts with this file or `CONTRIBUTING.md`, the repository wins.
