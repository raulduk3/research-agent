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

## Native comparison service

On 2026-09-21, the guest-only arm64 comparison image from the initial build was
exercised further as image
`sha256:811aa51c87b058ded9feb0ade4b503428ef01494f0653fba01a66e9925ee7c58`.
This image contains commit `8c604eb7efcbe1406859d07addb369c31fd120ae`.
That first pass established the fixture but did not exercise the later
authorization changes at the then-current commit
`9ae9250fb94755efc3ea2a215dc4d825cdef10ee`.

The committed `9ae9250` tree was then exported as an archive without working-tree
changes. Inside the guest, its production base reference alone was replaced by
the matching native arm64 `python:3.12.12-slim-bookworm` base already identified
above. The resulting comparison image was labelled with the full source commit
and resolved to
`sha256:53e675c70f8c4b6fdf9ec304a79c02c2ad918ab067324aa709ec76d8512876bd`.
The complete probe below passed against that exact image, so the latest committed
storage authorization changes were executed; `8c604eb` is historical comparison
evidence only.

The test used the existing pinned PostgreSQL 17.11 fixture and a fresh internal
Docker network shared only by PostgreSQL and the storage container. The storage
container ran as its `app` user with a read-only root filesystem, a writable
named artifact volume, read-only certificate/configuration binds, and no Docker
socket.

The fixture created a unique schema and unique deployment login and group roles.
It ran the repository's `migrate` and `provision_storage_roles` implementations,
then started `serve-storage` with the login assuming only the restricted
application group role. All passwords, the CA, server key and client keys were
generated and retained inside the disposable guest. No deployed identity or
credential was used.

The live HTTPS and database observations were:

- A client certificate signed by the fixture CA and mapped to a configured
  capability completed mTLS. An authenticated `jobs:claim` request traversed the
  real HTTP handler and PostgreSQL repository and returned HTTP 200 with status
  `ok`.
- The same mapped `reader` capability requested the `score` job kind owned by a
  different service role and was refused with HTTP 403 `forbidden` before a
  repository command ran.
- A fixture-CA-signed but unmapped certificate completed TLS and was refused by
  the application with HTTP 401 `unauthenticated`.
- A client with no certificate and a client signed by an untrusted fixture CA
  were both refused during TLS negotiation.
- The runtime login connected with the restricted application role and the
  unique schema as its current schema. PostgreSQL denied both `SET ROLE` to the
  migrator group and `TRUNCATE storage_schema_versions`.
- Starting the storage service with the migrator identity exited 1 before
  serving. `validate_runtime_role` refused it because that role can create schema
  objects.

These observations establish a native-arm64 engineering comparison of actual
service startup, mTLS authentication, capability rejection, a PostgreSQL-backed
command and cross-role denial. They do not qualify the production amd64 image,
replace deployment-generated credentials, or establish a collection-ready
network policy.

`bin/probe-storage-mtls` reproduces the service, mTLS, route-authorization and
database-role observations. It is opt-in and refuses to run unless the caller
explicitly supplies the Docker command and context, storage comparison image,
disposable PostgreSQL container and exact source commit. The image must be
Linux arm64 by default, or Linux amd64 with the explicit
`RESEARCH_AGENT_STORAGE_ARCHITECTURE=amd64` opt-in, and carry a matching
`research-agent.source-commit` label.
For the guest observation above, it was invoked as:

```console
RESEARCH_AGENT_CONTAINER_DOCKER=docker \
RESEARCH_AGENT_DOCKER_CONTEXT=rootless \
RESEARCH_AGENT_STORAGE_IMAGE=research-agent-storage:arm64-9ae9250 \
RESEARCH_AGENT_POSTGRES_CONTAINER=research-agent-pg-boundary \
RESEARCH_AGENT_SOURCE_COMMIT=9ae9250fb94755efc3ea2a215dc4d825cdef10ee \
python3 bin/probe-storage-mtls
```

The probe generates all credentials in its guest-local temporary directory,
uses unique resource and role names, and removes its container, network, volume,
schema and roles after a successful run. It does not build or qualify an image.

## Pinned amd64 build experiment

The emulated `uv sync` failure above does not prevent the pinned amd64 Python
runtime itself from executing in this guest. A guest-only Dockerfile experiment
used the committed `9ae9250` archive and three stages: the multi-architecture
`ghcr.io/astral-sh/uv:0.8.22` index at
`sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1`
provided the native `uv` binary; a native build-platform
`python:3.12.12-slim-bookworm` stage at multi-architecture index
`sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`
ran `uv export --locked --no-dev --no-install-package research-agent
--format requirements-txt`; and the unchanged production amd64 Python base
`sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301`
installed the generated requirements with `python -m pip install --no-cache-dir
--index-url https://pypi.org/simple --require-hashes --only-binary=:all:`.
The export included exact versions and hashes for `psycopg`, `psycopg-binary`,
`typing-extensions` and the Windows-conditional `tzdata`; pip selected the
hash-verified x86_64 `psycopg-binary` wheel. Neither a floating dependency nor
an emulated `uv` executable was used in the target stage.

The experimental image resolved to
`sha256:9e51fd469228add8ce08a3b5167d5ae12b5d451ed36daf99bb8e961e22febc07`
for `linux/amd64`. Under QEMU in the rootless guest, it reported `x86_64`, Python
3.12.12 and `psycopg` 3.2.10, printed the storage CLI, and completed the same
live HTTPS/database-role probe: mapped claim HTTP 200, mapped reader requesting
`score` HTTP 403, unmapped trusted certificate HTTP 401, absent/untrusted
certificates rejected at TLS, runtime role unable to assume the migrator or
truncate schema versions, and migrator service startup rejected. This establishes
that the committed application and pinned runtime/dependencies can execute on
amd64 through this build method. It is an experimental build, not a change to
the production Dockerfile or a deployment/collection admission result. The
suggested production change is to keep one `uv.lock` owner, export its hashed
requirements in a digest-pinned native build stage, and install those hashes
in the existing digest-pinned amd64 target. A final production change would
need its own review and exact-image checks.

The proposed Dockerfile was also validated against the later exact committed
snapshot `09a939ade56a650512d3d6e68c158120315195e2`, which adds NumPy 2.3.3
and SciPy 1.16.2 to the same lock. The tested proposal is retained outside the
repository at `/private/tmp/research-agent-proposed-Dockerfile`; no production
Dockerfile was changed. Its lock-export stage uses the pinned multi-architecture
Python index above with `--platform=$BUILDPLATFORM`, so an amd64 builder selects
its native amd64 manifest and an arm64 builder selects its native arm64
manifest. The final target still uses the original pinned amd64 manifest. It
also pins the Dockerfile frontend at
`sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32`
and preserves the original `/app/.venv/bin/python` entrypoint by creating that
venv before hash-verified pip installation.

The rootless guest built the exact `09a939a` snapshot in 100 seconds on its
warm cache, yielding `linux/amd64` image
`sha256:a2e5e5cea20db6d64ecbab1e1ad013f30d060a1c9b321a15e6e95f017037a2ef`.
The build's `uv export --locked` accepted the committed lock and pip selected
hash-verified x86_64 wheels for NumPy, SciPy and `psycopg-binary`. The image
reported x86_64 Python 3.12.12, NumPy 2.3.3, SciPy 1.16.2 and psycopg 3.2.10.
Its full mTLS/database-role probe passed with the same 200/403/401/TLS and
role-denial results above.

The image's `--version` command exits 1 because the existing version owner
derives the product version from Git tags and the runtime image contains no Git
checkout. That behavior is shared with the original Dockerfile and is separate
from dependency installation or storage startup. Embedding a version would
require a distinct contract decision and test.

The full gate remains unavailable by design: an evidence-marker file alone
still exits 1 after Compose rendering because host-network enforcement probes
are not implemented. The worker destination matrix, host firewall enforcement,
DNS and metadata denial, startup from the committed production Dockerfile,
and deployment qualification remain unproven.
