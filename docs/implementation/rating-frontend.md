# Private frontend scaffold

The first presentation slice of #73 updates the existing sign-in and blinded
digest templates. It uses the launch profile's FastAPI/Jinja2 rendering and
ordinary HTML forms, with no client framework or external assets. A shared
layout provides phone-sized reading, keyboard focus, the automated-output
notice and consistent form styling.

The digest displays only the title and abstract supplied by the existing blind
projection, followed by like, dislike and skip. Missing text and an empty digest
have explicit unavailable states. A persisted rating replaces that paper's controls with its recorded value.
Missing detail data remains explicitly unavailable.

## Recorded inspector views

The read-only inspector's existing population, agent, run and manifest pages
(#128) use a separate shared owner layout. It keeps the full stored identifiers,
genome parts, admission/archive records, run events, submissions and forecast
resolutions available without inventing a score or a successful run state.
Empty lists and missing genome records have explicit states. The run and
verdict lists retain each other's cursor when paging the inspector agent view.

The inspector layout is self-contained inside `web/inspect/templates`, so the
owner-session application's existing inspector-template search path (#255) can
reuse the population, run and manifest pages. The inspector routes and storage boundary remain unchanged. That
application's separate editable agent page is
outside this slice. Inspector links are not added to the blinded rater digest.
The owner application's separate agent page still needs the corresponding
independent-cursor fix when that work is integrated; the inspector change does
not silently replace its editable view.

## Integration boundary

This is an implementation scaffold, not study-readiness evidence. The app still
takes a `DigestFixture`; wiring the real daily digest and resolving stored paper
text remain unfinished in `web/digest.py`. The existing routes and submitted
identifiers also remain short of the TDD's opaque digest/entry view contract.

Reader sessions bind the stored principal, island and credential fingerprint.
Each protected request revalidates that binding. Rater principals are immutable
in the current storage schema; credential rotation/removal has no admitted
operator route yet. Explicit sign-out is the tested session-revocation path. The app requires an explicit
`RatingAppConfig.public_origin`; configure it to the trusted HTTPS origin of
the private listener, including its port. Both the request host and mutating
request Origin must match. A single-use cookie-bound pre-login CSRF token
protects sign-in; a `GET /login` that presents a live pre-login cookie reuses
its token, so a browser prefetch before the navigation does not invalidate the
rendered form, and only a sign-in POST or expiry rotates it. Session CSRF
tokens protect rating and sign-out. Sign-out
revokes the server session. Private responses use no-store and a restrictive
CSP; styles are packaged same-origin static files with no inline exceptions.

The configured digest carries its island and batch identity. A reader from
another island gets an empty queue; a composition root must supply their own
digest before they can rate it. The app validates the selected entry and derives
its paper identity. Storage independently checks the provisioned rater, normalized
island membership and entry-paper match in the rating transaction. Invalid
submissions create no rating or success event.

The rater-scoped persisted read follows #252's existing storage interface. A
reload or fresh sign-in shows the stored value, and duplicate submission cannot
overwrite it. The page does not claim that details have been unlocked: the
remaining detail/verdict work (#73) must supply that content. No agent identity,
origin, assessment or forecast is added to the pre-rating view.
Owner diagnostics, cost figures, reports and replay need their own established
reads and decisions before appearing as working controls.

The versioned API work (#249) is separate and must integrate the same authorized
handlers and saved-state fields before it can be validated with this branch.
A JSON interface does not itself change the launch profile's server-rendered
architecture.

## Verification

Run `bin/check --since develop` with the locked toolchain and an isolated
PostgreSQL 17 test database. The private-access and rating tests use real PostgreSQL and mTLS storage to
exercise sign-in, sign-out, saved-state reloads, replay, forged entry/paper/island
submissions, missing or hostile Origin, pre-login CSRF and session revocation.
Projection tests separately check the pre-rating field allowlist; they are not
evidence that the unfinished detail view or private-network deployment works. Inspect the rendered login,
populated digest, empty digest and missing-text states at phone and desktop
widths; visual inspection does not establish private-network deployment.

Rendered-template checks cover escaped paper text, preserved rating form values
and CSRF fields, the automated notice, empty and missing-text states, and the
sign-in error. Phone and desktop preview files were generated with illustrative
content. Browser visual inspection remains outstanding because the local-file
preview was refused by the browser's URL policy.

The inspector integration tests exercise its real storage reads. A focused
template test detects loss of the independent cursor when paging either the
run list or the verdict list, including the absence of a prior cursor.
