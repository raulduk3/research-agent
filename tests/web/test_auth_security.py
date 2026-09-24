from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from typing import cast
from uuid import UUID

import pytest

from research_agent.storage.client import StorageClient
from research_agent.web.auth import (
    AuthenticationError,
    PreLoginCSRFStore,
    RaterDirectory,
    RaterPrincipal,
    SessionStore,
    authenticate_session,
    hash_credential,
    verify_csrf,
    verify_origin,
)

RATER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class PrincipalStorage:
    def __init__(self, principals: tuple[RaterPrincipal, ...]) -> None:
        self._principals = principals

    def list_raters(self) -> tuple[RaterPrincipal, ...]:
        return self._principals


def directory(*principals: RaterPrincipal) -> RaterDirectory:
    storage = cast(StorageClient, PrincipalStorage(principals))
    return RaterDirectory(storage)


def principal(credential: str = "credential", *, island: str = "cs") -> RaterPrincipal:
    salt, credential_hash = hash_credential(credential)
    return RaterPrincipal(RATER_ID, island, salt, credential_hash)


def test_origin_requires_the_configured_scheme_host_and_port() -> None:
    verify_origin("https://rating.example", "https://rating.example")
    verify_origin("https://RATING.example:443", "https://rating.example")

    for refused in (
        None,
        "null",
        "http://rating.example",
        "https://other.example",
        "https://rating.example:444",
        "https://user@rating.example",
        "https://rating.example/path",
        "https://rating.example?query=yes",
    ):
        with pytest.raises(AuthenticationError):
            verify_origin(refused, "https://rating.example")


def test_invalid_configured_origin_is_a_configuration_error() -> None:
    with pytest.raises(ValueError):
        verify_origin("https://rating.example", "rating.example")


def test_prelogin_csrf_token_is_cookie_bound_and_single_use() -> None:
    store = PreLoginCSRFStore()
    token = store.issue()

    with pytest.raises(AuthenticationError):
        store.consume("another-cookie", token.form_token)
    store.consume(token.cookie_token, token.form_token)
    with pytest.raises(AuthenticationError, match="already used"):
        store.consume(token.cookie_token, token.form_token)


def test_prelogin_csrf_mismatch_consumes_that_cookie_token() -> None:
    store = PreLoginCSRFStore()
    token = store.issue()

    with pytest.raises(AuthenticationError, match="does not match"):
        store.consume(token.cookie_token, "forged")
    with pytest.raises(AuthenticationError, match="already used"):
        store.consume(token.cookie_token, token.form_token)


def test_unicode_prelogin_csrf_token_is_refused_as_authentication_error() -> None:
    store = PreLoginCSRFStore()
    token = store.issue()

    with pytest.raises(AuthenticationError, match="does not match"):
        store.consume(token.cookie_token, "forged-\N{SNOWMAN}")


def test_concurrent_prelogin_csrf_replay_has_exactly_one_success() -> None:
    store = PreLoginCSRFStore()
    token = store.issue()
    barrier = Barrier(2)

    def consume() -> bool:
        barrier.wait()
        try:
            store.consume(token.cookie_token, token.form_token)
        except AuthenticationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: consume(), range(2)))

    assert sorted(outcomes) == [False, True]


def test_prelogin_csrf_token_expires() -> None:
    store = PreLoginCSRFStore()
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = store.issue(now=issued_at)

    with pytest.raises(AuthenticationError, match="expired"):
        store.consume(
            token.cookie_token,
            token.form_token,
            now=issued_at + timedelta(minutes=11),
        )


def test_prelogin_csrf_current_reuses_a_live_token_until_consumed_or_expired() -> None:
    store = PreLoginCSRFStore()
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = store.issue(now=issued_at)

    assert store.current(token.cookie_token, now=issued_at) == token
    assert store.current(token.cookie_token, now=issued_at) == token
    assert store.current("another-cookie", now=issued_at) is None
    assert store.current(None, now=issued_at) is None
    later = issued_at + timedelta(minutes=11)
    assert store.current(token.cookie_token, now=later) is None
    store.consume(token.cookie_token, token.form_token, now=issued_at)
    assert store.current(token.cookie_token, now=issued_at) is None


def test_bound_session_revalidates_the_current_principal() -> None:
    current = principal()
    current_directory = directory(current)
    store = SessionStore()
    session = store.issue(current)

    assert (
        authenticate_session(store, session.session_id, directory=current_directory)
        is session
    )
    assert session.island == current.island
    assert session.credential_fingerprint == current.credential_fingerprint


def test_unicode_session_csrf_token_is_refused_as_authentication_error() -> None:
    session = SessionStore().issue(RATER_ID)

    with pytest.raises(AuthenticationError, match="does not match"):
        verify_csrf(session, "forged-\N{SNOWMAN}")


def test_rotated_credential_invalidates_and_revokes_a_bound_session() -> None:
    original = principal("old credential")
    rotated = principal("new credential")
    store = SessionStore()
    session = store.issue(original)

    with pytest.raises(AuthenticationError, match="absent or changed"):
        authenticate_session(store, session.session_id, directory=directory(rotated))
    assert store.get(session.session_id) is None


def test_deleted_principal_invalidates_and_revokes_a_bound_session() -> None:
    current = principal()
    store = SessionStore()
    session = store.issue(current)

    with pytest.raises(AuthenticationError, match="absent or changed"):
        authenticate_session(store, session.session_id, directory=directory())
    assert store.get(session.session_id) is None


def test_changed_island_invalidates_a_bound_session() -> None:
    current = principal(island="cs")
    moved = RaterPrincipal(
        current.rater_id,
        "quant_ph",
        current.salt,
        current.credential_hash,
    )
    store = SessionStore()
    session = store.issue(current)

    with pytest.raises(AuthenticationError, match="absent or changed"):
        authenticate_session(store, session.session_id, directory=directory(moved))


def test_legacy_unbound_session_remains_usable_without_directory_revalidation() -> None:
    store = SessionStore()
    session = store.issue(RATER_ID)

    assert authenticate_session(store, session.session_id) is session
    with pytest.raises(AuthenticationError, match="absent or changed"):
        authenticate_session(
            store,
            session.session_id,
            directory=directory(principal()),
        )
