# Private rating frontend

The first presentation slice of #73 updates the existing sign-in and blinded
digest templates. It uses the launch profile's FastAPI/Jinja2 rendering and
ordinary HTML forms, with no client framework or external assets. A shared
layout provides phone-sized reading, keyboard focus, the automated-output
notice and consistent form styling.

The digest displays only the title and abstract supplied by the existing blind
projection, followed by like, dislike and skip. Missing text and an empty digest
have explicit unavailable states. Form endpoints, session handling, CSRF fields
and rating values remain the existing application's responsibility.

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
