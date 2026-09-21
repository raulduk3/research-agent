# Disposable Linux boundary evidence

This is a local engineering observation, not a collection-readiness record or
deployment binding. It was made on 2026-09-20 in an isolated Lima VZ guest:
`LIMA_HOME=/private/tmp/research-agent-lima.eIDic1/home`, instance
`research-agent-boundary`. The guest has no host mounts and uses rootless Docker.
Its forwarded Docker socket is
`/private/tmp/research-agent-lima.eIDic1/home/research-agent-boundary/sock/docker.sock`.
The guest is Ubuntu 26.04 on arm64, with two CPUs, 4 GiB memory and a 20 GiB
ephemeral disk.

## Observed runtime boundaries

`bin/check-collection-linux --runtime-probe` ran in that guest with the pinned
`busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0`
test image. It created and removed its own internal Docker network, named volume
and container. Docker inspection showed the network was internal and the only
container mount was the named artifact volume. The container had no Docker
socket, and TCP connections to `1.1.1.1:443` and `169.254.169.254:80` failed.
Failed connections alone cannot distinguish an enforcement rule from an
unavailable destination; the full firewall and role-destination matrix remains
required. This probe is not the collection admission gate.

The exact pinned PostgreSQL 17.11 image in `compose.yaml` started under the same
rootless runtime. A temporary role matrix observed that a schema owner could
alter an existing table, while a restricted application role could select from
immutable rows but was denied update, delete, truncate, schema-version insert,
table alteration and function creation. The original immutable row remained.
These are disposable fixture roles and data, not deployed identities.

## Emulation limits

The production Python base digest is valid: pulling
`python:3.12.12-slim-bookworm@sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301`
with `--platform linux/amd64` succeeded. Lima Rosetta was enabled, but rootless
execution exited 133 with `Failed to find vdso DT_HASH`; its documented CDI
device was unavailable. Guest-only QEMU user emulation ran `python --version`,
but the production image build failed in `uv sync` with `qemu: uncaught target
signal 11` and exit 139. A rootful-Docker fallback was rejected by the local
approval control and was not executed.

For comparison only, a guest-only arm64 image built from the identical committed
source after replacing the architecture-specific base digest with the matching
upstream `python:3.12.12-slim-bookworm` tag. It built and printed the storage
CLI help. Its resolved arm64 base digest was
`sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`;
it cannot qualify the pinned amd64 deployment image.

The full gate remains unavailable by design: an evidence-marker file alone
still exits 1 after Compose rendering because host-network enforcement probes
are not implemented. No actual storage-service image startup, mTLS exchange,
or deployment qualification is claimed by this observation.
