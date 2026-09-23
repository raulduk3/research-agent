# Private frontend scaffold

The first presentation slice of #73 updates the existing sign-in and blinded
digest templates. It uses the launch profile's FastAPI/Jinja2 rendering and
ordinary HTML forms, with no client framework or external assets. A shared
layout provides phone-sized reading, keyboard focus, the automated-output
notice and consistent form styling.

The digest displays only the title and abstract supplied by the existing blind
projection, followed by like, dislike and skip. Missing text and an empty digest
have explicit unavailable states. Form endpoints, session handling, CSRF fields
and rating values remain the existing application's responsibility.

## Recorded inspector views

The read-only inspector's existing population, agent, run and manifest pages
(#128) use a separate shared owner layout. It keeps the full stored identifiers,
genome parts, admission/archive records, run events, submissions and forecast
resolutions available without inventing a score or a successful run state.
Empty lists and missing genome records have explicit states. The run and
verdict lists retain each other's cursor when paging the inspector agent view.

The inspector layout is self-contained inside `web/inspect/templates`, so the
owner-session application's existing inspector-template search path (#255) can
reuse the population, run and manifest pages. No route, authorization or
storage boundary changes. That application's separate editable agent page is
outside this slice. Inspector links are not added to the blinded rater digest.
The owner application's separate agent page still needs the corresponding
independent-cursor fix when that work is integrated; the inspector change does
not silently replace its editable view.

## Integration boundary

This is an implementation scaffold, not study-readiness evidence. The app still
takes a `DigestFixture`; wiring the real daily digest and resolving stored paper
text remain unfinished in `web/digest.py`. The existing routes and submitted
identifiers also remain short of the TDD's opaque digest/entry view contract.

The presentation does not infer rating progress, hide an entry after a rating,
or claim that details have been unlocked. Rater-specific rating reads (#252)
and the remaining detail/verdict work (#73) must supply those states. No agent
identity, origin, assessment or forecast is added to the pre-rating view.
Owner diagnostics, cost figures, reports and replay need their own established
reads and decisions before appearing as working controls.

The versioned API work (#249) is separate. A JSON interface does not itself
change the launch profile's server-rendered architecture.

## Verification

Run `bin/check --since develop` with the locked toolchain and an isolated
PostgreSQL 17 test database. The existing private-access and rating tests cover
authentication, CSRF, storage writes and disclosure. Inspect the rendered login,
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
