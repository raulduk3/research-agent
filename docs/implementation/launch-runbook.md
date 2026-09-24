# Launch runbook: from merged develop to the first live batch

Written 2026-09-23 for #312 against `develop` as of the 2026-09-23 day
branch, and revised for #356 against the same day branch after the
2026-09-24 bring-up. One numbered sequence, in the order the specification
and the code require. Every command named here exists in `bin/`, in
`deploy/` or in `python -m research_agent`; where a step has no command, the
step says so and cites the issue that owns the gap. Only the storage
bring-up of step 11 has been run end to end; the rest is the path, not
evidence that the path works.

Each step names who runs it:

- **Operator**: a command in this repository, run on the application host
  (or the rented graphics host where the step says so).
- **Owner**: an action only the owner takes: a merge, a decision, a
  credential, a funding authorization, a rented machine.
- **Gate**: evidence the owner satisfies outside the repository and records
  under `docs/evidence/` or on an issue; no command produces it.

`DSN` below always selects a dedicated schema, and `STATE` is the local state
directory the same command family used before (`bin/corpus-pilot`,
`bin/build-corpus` and `bin/daily` each keep certificates, artifacts and
measurements there). No credential appears in a command line: provider keys
are read from the environment only.

## 1. Merge the day branch

1. **Owner.** Merge the day's pull request (`loop/<date>` into `develop`),
   then update the checkout:

   ```sh
   git switch develop && git pull --ff-only
   bin/check --since develop
   ```

   Produces: a `develop` head that carries every folded change.
   Worked when: `bin/check` exits 0 on that head (lock, lint, format, strict
   typing, tests and the specification checks). `RESEARCH_AGENT_TEST_DSN`
   must point at a disposable PostgreSQL 17 database, or the database checks
   fail by design.

## 2. Corpus data

The detailed owners and flags are in [corpus-release.md](corpus-release.md)
and [remote-embedding.md](remote-embedding.md); this is their launch order.

2. **Operator.** Acquire documents and citation labels for the release
   population, labels first:

   ```sh
   bin/corpus-pilot run --state PILOT --dsn "$PILOT_DSN" \
     --population-rule "<the owner's population rule from #66>" \
     --cap 10000 --seed <the owner's recorded seed> --per-month 0 \
     --gate-on-labels [--record-cap N]
   bin/corpus-pilot report --state PILOT --dsn "$PILOT_DSN"
   ```

   Produces: committed `openalex` (citation observation and resolved labels)
   and `documents` jobs per family.
   Worked when: the report's `gate` summary shows `labeled` equal to
   `selected` (every family's labels resolved or refused) and `acquired`
   equal to `labeled - gated_out` (every family that passed the gate has
   its documents). With `--gate-on-labels` no documents arrive until the
   labels do (#151); a killed run resumes by rerunning the same command.
   The population rule is the owner's open decision on #66; the command
   refuses a blank one.

3. **Operator.** Export the extracted text:

   ```sh
   bin/export-text --state PILOT --dsn "$PILOT_DSN" --out ./text
   ```

   Produces: one `PaperText` JSON per paper version in `./text` and
   `./text/export-manifest.canonical`.
   Worked when: the manifest's count per coverage accounts for every
   committed `documents` family; failed or `unavailable` versions are listed
   there with their reason. Needs poppler's `pdftotext` on `PATH` for
   PDF-only sources.

4. **Owner, then operator.** Rent a graphics host (a spend decision under
   Appendix A; see [authorization-status.md](../evidence/funding/authorization-status.md)),
   copy `./text` to it over SSH, and embed there:

   ```sh
   bin/embed-batch --text ./text --out ./vectors --device cuda
   ```

   Produces: one vector file per paper version and `./vectors/manifest.json`.
   Worked when: every `*.json` in `./text` has a vector file; a killed batch
   resumes from what `--out` already holds. Copy `./vectors` back.
   `--device mps` or `cpu` on the application host is the same command
   without a rental.

5. **Operator.** Gate the batch on platform agreement and store the
   embedding views:

   ```sh
   bin/import-embeddings --in ./vectors --namespace ./index --text ./text \
     --check 25 --state PILOT --dsn "$PILOT_DSN"
   ```

   Produces: the published `./index` namespace and one stored embedding view
   per version.
   Worked when: it prints `published N paper versions ... min cosine X` with
   X at or above the manifest threshold (default 0.9999) and `stored M
   embedding views`, then `namespace identity <sha256>`, the identity step
   20 binds. A refusal means the batch is not used in step 6.
   Rerunning the same command over the same batch, with any `--check`,
   reuses every published entry and stores only the views not yet current.
   To store the views of a namespace published without `--state`, run
   `bin/import-embeddings --views-only --in ./vectors --namespace ./index
   --text ./text --state PILOT --dsn "$PILOT_DSN"`: it measures and
   publishes nothing and is refused if any version of the batch is not
   published (#361).
   Record the measured agreement under
   [remote-embedding.md#Recorded agreement](remote-embedding.md).

6. **Operator.** Build the acquisition-pilot and initial-fit releases:

   ```sh
   bin/release-candidates --state PILOT --dsn "$PILOT_DSN" \
     --corpus-state CORPUS --corpus-dsn "$CORPUS_DSN" \
     --purpose initial_fit --out fit-candidates.json
   bin/build-corpus run --state CORPUS --dsn "$CORPUS_DSN" \
     --population-rule "<rule from #66>" \
     --representation-hash <sha256 of the pinned embedding manifest> \
     --purpose initial_fit --release-id initial-fit \
     --candidates fit-candidates.json \
     --embeddings ./vectors --text ./text [--model-cache-dir DIR]
   bin/build-corpus report --state CORPUS --dsn "$CORPUS_DSN" \
     --population-rule "<rule from #66>" --representation-hash <sha256> \
     --release-id initial-fit
   ```

   Repeat both commands with `--purpose acquisition_pilot` and
   `--release-id pilot` for the pilot release, into the same `CORPUS`
   schema.
   Produces: a candidates file with its `candidates_hash`, and per release a
   committed `label` job whose summary names `release_artifact_hash` and the
   coverage report hash.
   Worked when: `bin/release-candidates` prints `unobserved` 0 (or the
   count of families no snapshot labels pass observed, whose labels stay
   unknown), the report lists both hashes and the coverage report shows
   `features_complete` for the rows the batch covered.
   `bin/release-candidates` draws each purpose's population from the
   acquired families with the contract's seed (20260920) and intended count
   (pilot 100, initial fit 2000), whatever seed and cap the acquisition
   used; pass the pilot's candidates file as `--exclude` for the initial
   fit. Its report prints the pool, the drawn count, every stratum and the
   shortfall.
   Gaps: a pool acquired over fewer weeks than the initial fit's 100 leaves
   the rest as shortfall
   ([corpus-release.md#Known limits](corpus-release.md)).

## 3. Heads

7. **Operator.** Fit, calibrate, qualify and bundle the three heads:

   ```sh
   bin/fit-heads --state CORPUS --dsn "$CORPUS_DSN" \
     --release <initial_fit release_artifact_hash> \
     --pilot-release <acquisition_pilot release_artifact_hash>
   ```

   Produces: the qualification report, the bundle and the promotion
   decision; the command prints the report path, the bundle id and file,
   the decision path and the promoted targets. The qualification report is
   stored where that printed path says; keep it with the release hashes.
   Worked when: the promotion decision names each target it promotes; a
   target the qualification refuses stays out of the bundle. It activates
   nothing, spends nothing and downloads nothing.

8. **Operator.** Activate the bundle step 7 wrote:

   ```sh
   bin/activate-bundle --bundle <bundle file> --decision <promotion decision> \
     --dsn "$CORPUS_DSN" --artifacts CORPUS/artifacts
   ```

   Produces: one published head per qualified target, the serving manifest
   and an activation record; the command prints the record, the active
   bundle and its generation. Worked when: the printed active bundle is the
   one the model service loads. It refuses a bundle or decision the store
   did not commit, and a served target that was not promoted unless
   `--allow-unpromoted REASON` names why; the record keeps the reason.
   Running it again on the active bundle reports it and writes nothing.

## 4. The Linux boundary

9. **Owner.** Provide the application host. The host is sized from measured
   demand (#105) and is still unset in
   [bindings-2026-09-22.md](../evidence/deployment/bindings-2026-09-22.md).
   The committed Lima guest is evidence apparatus, not the deployment target:

   ```sh
   limactl start --name=research-agent-boundary \
     docs/implementation/lima-collection-boundary.yaml
   ```

   It starts a disposable aarch64 guest with x86-64 translation, no host
   mount, no forwarded Docker socket and no credential. Use it to rerun the
   boundary gate (step 12), not to serve the launch.

10. **Operator.** Build and record the one application image (#316):

    ```sh
    bin/build-image
    ```

    Produces: the image built from the root `Dockerfile`, labeled with its
    build manifest hash and product version, and `deploy/images.json`
    holding the digest the engine reports, the source commit and the build
    manifest. Worked when: it prints
    `RESEARCH_AGENT_IMAGE_DIGEST=<digest>`, the value `deploy/compose.yaml`
    selects every application service by. It refuses a working tree with
    uncommitted changes and pushes nothing. The image's entry point,
    `python -m research_agent`, serves `migrate`, `check-schema`,
    `collection-readiness`, `serve-storage`, `bind-anchor` and the role
    commands of #315 (`serve-models`, `serve-owner`, `serve-rating`,
    `serve-ingest`, `provision-launch-roles`).
    Gap: the tool service's HTTP surface and client exist
    (`tools/http.py`), but there is no `serve-tools` command, and
    `deploy/compose.yaml` keeps `tools` under the `unlaunched` profile with
    no command (#323).

11. **Owner, then operator.** Bring up storage with its secrets and
    certificates. Two Compose files exist, for two purposes:

    - `compose.yaml` (root) is a storage-only stack for development: pinned
      `postgres:17.11` and the storage service built from the `Dockerfile`,
      with seven secrets read from files named by
      `RESEARCH_AGENT_POSTGRES_DATABASE_FILE`,
      `RESEARCH_AGENT_POSTGRES_USER_FILE`,
      `RESEARCH_AGENT_POSTGRES_PASSWORD_FILE`,
      `RESEARCH_AGENT_STORAGE_DSN_FILE`,
      `RESEARCH_AGENT_STORAGE_TLS_CERTIFICATE_FILE`,
      `RESEARCH_AGENT_STORAGE_TLS_PRIVATE_KEY_FILE` and
      `RESEARCH_AGENT_STORAGE_TLS_CLIENT_CA_FILE`, and the storage
      configuration from `RESEARCH_AGENT_STORAGE_CONFIG`
      (shape: [storage-config.example.json](storage-config.example.json)).
    - `deploy/compose.yaml` is the deployment. It declares every role,
      including the owner app and the ingress (decision 0030), with their
      networks, Appendix A ceilings, health checks and secrets. It needs
      the digest step 10 printed, the Caddy digest
      (`RESEARCH_AGENT_INGRESS_DIGEST`) and the profile's public hostname in
      the environment, and `platform.compose` checks it. `owner` and
      `ingest` read the database directly, so both sit on the `storage`
      network beside PostgreSQL (#349).

    One command writes everything `deploy/compose.yaml` mounts (#342), into
    a directory outside the repository:

    ```sh
    bin/stack-config /absolute/path/profile.json /absolute/path/stack \
      --ingress-digest <pinned Caddy sha256> [--values /absolute/path/values.json]
    ```

    Pin image index digests, not single-platform manifest digests, so the
    same pin runs natively on amd64 and arm64 hosts (#347). `postgres:17.11`
    is pinned to its index in both Compose files; for `caddy:2.10` pass
    `c3d7ee5d2b11f9dc54f947f68a734c84e9c9666c92c88a7f30b9cba5da182adb`.
    `docker buildx imagetools inspect <image>` prints the index digest.

    It refuses a profile that fails `bin/check-profile` or has no
    `host.public_hostname`, a missing `deploy/images.json`, and an output
    directory inside the repository. It writes `certs/` (by calling
    `bin/issue-certs`, once), `secrets/` (PostgreSQL credentials for the
    compose superuser and two login roles, generated once, and the DSN files
    derived from them on every run), `config/` (the profile, one
    `<service>.json` per application role, with producer, profile hash,
    storage client block and scopes, `storage.json` carrying a capability
    per issued client certificate, and `roles.json` for
    `provision-launch-roles`), `sql/` (`schema.sql` and `logins.sql`,
    owner-only because the second holds the login passwords) and
    `compose.env`. A rerun keeps certificates and secrets, rewrites configs
    and prints what changed; it never prints a secret. Rerun it after any
    profile change, such as the final `host.front_end_origin` of step 22.

    The model service runs in a container only where the host's graphics
    device reaches one: `compose.env` sets
    `COMPOSE_PROFILES=models-container`, which starts it. On a Mac the device
    is Metal, which no container reaches (Docker Desktop fails with
    `failed to discover GPU vendor from CDI`, and the launcher refuses with
    `no host graphics device is available`). There, add `--models-native`
    (#350): `compose.env` leaves the profile off and maps `models` to the
    host gateway in the model service's clients (`extra_hosts`), and the
    command writes `config/models.native.json`, which names the host path of
    the profile and a `secrets_root` of `STACK/native`, whose
    `run/secrets/` holds the service's secret mounts as links into
    `certs/`. The printed steps then start the service on the host before
    the stack, with
    `python -m research_agent serve-models --config STACK/config/models.native.json`,
    listening on port 8443 of every host address, so that port must be
    free; only the admitted client certificates reach it. Gap: the
    services network is internal, and an internal network does not route
    to the host gateway. `ingest` also joins `egress` and reaches the host.
    Reader, tools, scorer and orchestrator are unlaunched and need a route
    to the host when they are launched.

    The storage schema is `research_agent` (the profile's storage section
    names none, #348): every generated DSN selects it with
    `options=-csearch_path=research_agent`, and `storage.json` and
    `roles.json` name it as `schema`. The DSNs connect as three identities:
    `postgres_dsn` as the compose superuser, for provisioning and the first
    migration only; `storage_dsn`, `ingest_database_dsn` and
    `owner_database_dsn` as `research_agent_runtime`, a login in the
    `research_agent_application` group; `migrator_dsn` as
    `research_agent_migration`, a login in the `research_agent_migrator`
    group, for later migrations and `check-schema`. The storage service
    refuses the superuser, and `provision-launch-roles` refuses a schema
    PUBLIC can use.

    `--values` merges operator-held launcher values per service, such as
    `app`'s `digest` and `public_origin` and `ingest`'s
    `agent_model_manifest` and `index_identities`; the command names each
    one still missing. `ZAI_API_KEY` and `JEV_API_KEY` are not written: no
    launcher declares a provider-key secret, so the run command reads them
    from its own environment. The command prints the lines that follow,
    with its output directory filled in (`COMPOSE` stands for
    `docker compose --env-file STACK/compose.env -f deploy/compose.yaml`).
    PostgreSQL publishes no host port, so every step runs on the compose
    network. In order: the schema, the migration, the group roles, the
    logins, the schema check, the stack:

    ```sh
    COMPOSE up -d postgres
    COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U research_agent -d research_agent < STACK/sql/schema.sql
    RESEARCH_AGENT_STORAGE_DSN="$(cat STACK/secrets/postgres_dsn)" COMPOSE run --rm --no-deps -e RESEARCH_AGENT_STORAGE_DSN storage migrate
    COMPOSE run --rm --no-deps -v STACK/config/roles.json:/run/config/roles.json:ro -v STACK/config/profile.json:/run/config/profile.json:ro -v STACK/secrets/postgres_dsn:/run/secrets/postgres_dsn:ro storage provision-launch-roles --config /run/config/roles.json
    COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U research_agent -d research_agent < STACK/sql/logins.sql
    RESEARCH_AGENT_STORAGE_DSN="$(cat STACK/secrets/migrator_dsn)" COMPOSE run --rm --no-deps -e RESEARCH_AGENT_STORAGE_DSN storage check-schema
    COMPOSE up -d
    ```

    `schema.sql` creates the schema the migrations assume, owned by the
    compose superuser, and revokes it from PUBLIC. `migrate` runs as the
    superuser because the migration login does not exist yet.
    `provision-launch-roles` creates the two hardened group roles, moves
    the schema's objects to the migrator group and grants the application
    group its runtime privileges; it refuses a database whose PostgreSQL
    major version is not the launch profile's and runs once, on the freshly
    migrated schema. `logins.sql` then creates the two `INHERIT` logins and
    grants each its group. Later migrations use `migrator_dsn`.

    Worked when: `check-schema` prints `Storage schema is current.` and
    every started service reports healthy. Never run the storage service as
    the migrator identity. The sequence above is the first bring-up only.
    On every later one, run `check-schema` first with `migrator_dsn` and
    run `migrate`, with the same DSN, only when it fails. `migrate` applies,
    in one transaction, only the migrations whose version
    `storage_schema_versions` does not yet record, and refuses a non-migrator
    identity on a current schema (#352).

    The `models` service reserves one container graphics device. On a host
    whose graphics device does not reach a container (an Apple silicon
    host, for one), `COMPOSE up -d` cannot place it: start the stack
    without it and run
    `python -m research_agent serve-models --config /absolute/path/models.json`
    natively on the host. No mode yet makes that the configured path
    (#350).

12. **Operator.** Rerun the boundary gate on the host's engine:

    ```sh
    bin/check-collection-linux --worker-boundary
    uv run --locked python -m research_agent collection-readiness \
      --storage-config /absolute/path/storage.json \
      --isolation-evidence <evidence file>
    ```

    Worked when: the gate passes and `collection-readiness` prints
    `Collection readiness is evidenced; start remains operator-owned.`
    Without `--worker-boundary` the gate reports unavailable by design.
    Record what was observed the way
    [linux-boundary-evidence.md](linux-boundary-evidence.md) did.

13. **Owner.** Write the launch profile JSON. It is a closed object:
    unknown or missing fields are refused (`platform/profile.py#LaunchProfile.from_json`).
    Start from the committed
    [launch-profile.example.json](launch-profile.example.json), which carries
    every field at its Appendix A launch value: retention of two years (the
    study duration plus two), the `arxiv` and `openalex` licensed sources from
    [source-permissions.md](../evidence/permissions/source-permissions.md),
    Appendix A's disabled-for-launch capabilities, and funding unauthorized.
    `bin/check-profile FILE` validates a profile, prints its hash and lists
    every field that differs from the example.

    Every boolean starts `false` and turns `true` only when the step that
    evidences it has passed: `agent_qualification_passed` after step 15,
    `backup_verified` and `anchor_endpoint_bound` after step 14,
    `replay_integrity_verified` after a verified replay, and
    `paid_execution_enabled` with `funded` only when the owner records a
    funding authorization (**Gate**; none exists today, see
    [authorization-status.md](../evidence/funding/authorization-status.md)).
    Worked when:

    ```sh
    uv run --locked python -c "from pathlib import Path; \
    from research_agent.platform.profile import LaunchProfile; \
    print(LaunchProfile.from_json(Path('profile.json').read_bytes()).readiness('study'))"
    ```

    prints `()`. Any name it prints is an unmet gate. Until the profile is
    funded, `orchestration/bindings.py#remaining_spend` is zero and
    `bin/daily` draws no runs.

14. **Owner.** Provide the backup destination and the anchor receiver host
    (SR-16), a separate machine the owner rents and binds. Both are unset
    ([bindings-2026-09-22.md](../evidence/deployment/bindings-2026-09-22.md)).
    Once the receiver runs, bind it from the storage service's
    configuration:

    ```sh
    python -m research_agent bind-anchor --storage-config /absolute/path/storage.json \
      --receiver https://<receiver host> --verify
    ```

    Worked when: it records the binding after one acknowledged round trip;
    it records nothing without `--verify`. Then set `anchor_endpoint_bound`.
    Gap: no command binds, writes to or verifies the backup destination,
    and restore verification is #74's acceptance.

## 5. Qualification

15. **Operator, with the owner's key.** Run the agent-model battery live:

    ```sh
    ZAI_API_KEY=<set in the environment, never on the line> \
    bin/qualify-inference --endpoint <chat-completions URL> \
      --processor-dir <pinned tokenizer dir> [--revision REV] \
      [--day-cap-usd 8.00 --month-cap-usd 200.00]
    ```

    Produces: an immutable report under `docs/evidence/inference-capacity/`
    (the 2026-09-22 file there is a labeled dry run, not a result).
    Worked when: all three suites report a passing verdict at their full
    populations (100 conversations with at least 99 valid, 50 figure/table
    questions at 80%, 100 evidence-location questions at 90% per context
    length). Then set `agent_qualification_passed` in the profile. This is
    paid execution: it reserves against the caps before each conversation.

16. **Operator, with the owner's key, then owner review.** The RD-22 Jev
    smoke test:

    ```sh
    JEV_API_KEY=<set in the environment, never on the line> \
    bin/jev-smoke --state DIR --release <sha256> --rubric jev-rubric-v2 \
      --candidates candidates.json --text <bin/export-text dir> \
      --provider provider.json --dsn "$DSN"
    ```

    `provider.json` declares the `JevProviderConfig` fields (endpoint,
    configured model, verified revisions, capability evidence hash, input
    token limit, prompt price, daily sublimit, `smoke_revision`) and holds no
    credential. Produces: the frozen sample and the smoke report as artifacts
    in `DIR/artifacts`, with every request and response the worker stored.
    It prints the report hash and each field's valid count and answer counts.
    Worked when: every field shows at least 18 valid results of 20. A rerun
    reuses committed answers and prints the same report hash. Without
    `JEV_API_KEY` it is a dry run on the recorded fixture, stored under
    `DIR/jev-smoke-dry-run`, and is not the smoke test. This is paid
    execution under the Jev operating limits. The live rubric run in
    [jev-smoke-2026-09-23.md](../evidence/models/jev-smoke-2026-09-23.md) is
    provider evidence, not the RD-22 smoke.
    Gap: the stored report carries no owner review, and no command records
    one, so `measurement/jev.py#check_smoke_activation` still refuses
    activation (#61, #62).

17. **Gate.** Retrieval qualification (MD-12, RD-28): the fixed
    100-paper, 500-question evaluation with two independent reviewer
    judgments per question. The reviewer plan is
    [retrieval-qualification-reviewers.md](../evidence/reviewer-operations/retrieval-qualification-reviewers.md).
    Draw and score it against the published index:

    ```sh
    bin/qualify-retrieval sample --state DIR --release <sha256>
    bin/qualify-retrieval score --state DIR --release <sha256> \
      --namespace ./index --text ./text --questions FILE [--cache-dir DIR]
    ```

    `sample` stores and lists the 100-paper draw for the question authors;
    `score` stores the report as an artifact. Worked when: `score` prints
    pass and exits 0 (1 on fail or incomplete, 2 on a refused input). No
    paid call. Gap: `publish_index` still never marks an index
    study-qualified; #74 consumes the evidence.

## 6. SR-17 activation

18. **Owner.** Admit each layer. `platform/readiness.py#evaluate_admission`
    decides one layer against a registered baseline and a comparison report
    whose registration precedes its execution; decision 0024 admits the Jev
    layer (`jev_admitted`), and the future prediction heads stay denied
    whatever is passed. Record each qualification report, then admit over
    the stored reports (#324):

    ```sh
    python -m research_agent.platform.reports record --dsn "$DSN" \
      --artifact-root DIR --kind KIND --report FILE \
      --primary-metric METRIC --registered-at UTC [--executed-at UTC]
    python -m research_agent.platform.reports admit --dsn "$DSN" \
      --artifact-root DIR --layer ID --candidate <sha256> [--baseline <sha256>] \
      --primary-metric METRIC --scope SCOPE [--jev-admitted]
    ```

    Worked when: `admit` prints the admission record and exits 0; it exits
    1 when it denies and names every report kind with no stored report.
    Gap: `assessments/readiness.py#check_assessment_readiness` (RD-24) has
    no entry point. Study activation as a whole is #74.

## 7. The first day

19. **Owner.** Seed the population from the committed fixture (#311,
    [docs/launch/README.md](../launch/README.md)): eight procedures in each
    of the three islands, twenty-four genomes, the evidence-first procedure
    as each island's founder:

    ```sh
    bin/seed-population --file docs/launch/seeds.json --state DAILY \
      --dsn "$DSN" --profile profile.json [--island cs|quant-ph|q-bio] \
      [--corpus-ids FILE]
    ```

    Produces: the admission events in `DAILY/artifacts`. Worked when: it
    prints each configuration hash as `admitted` or `present`, then each
    island's population; a second run admits nothing. It checks the whole
    fixture before writing, and a genome carrying a corpus paper identifier
    (AG-31) or an island with a different founder stops it with nothing
    admitted. Without the founders `bin/daily` issues no run.

20. **Operator.** Bind the day, then issue it. The first day has no sealed
    snapshot, so its index identity is that of each namespace
    `bin/import-embeddings` published (step 5 prints it last;
    `bin/import-embeddings --print-identity --namespace DIR` prints it
    again). Every later day reads the latest snapshot's with `--dsn "$DSN"`
    in place of `--namespace`:

    ```sh
    bin/bindings --profile profile.json --endpoint <chat-completions URL> \
      --image storage=<sha256> [--image ROLE=<sha256> ...] \
      --namespace <namespace dir> > bindings.json
    bin/daily --state DAILY --dsn "$DSN" --profile profile.json \
      --bindings bindings.json [--since YYYY-MM-DD] [--device cuda|mps|cpu]
    ```

    `--since` is required on the first day only. `$DSN` is the storage
    service's runtime DSN. `bin/daily` never migrates: the schema must
    already be current (step 11's `migrate`, then `check-schema`, under
    `migrator_dsn`), and a stale schema exits 1 with its reason before the
    day's window is recorded. Produces: the day's
    listings, acquired papers, cards, sealed sheets and snapshot, each
    island's coverage draw and one run record per sampled paper and active
    genome, and `DAILY/watermark.json`. It starts no run.
    `bin/bindings` writes the agent model manifest hash `bin/run-agent`
    pins, the image digests and the index identities; every application
    role runs the one image, so each `--image` takes the `image_digest` in
    `deploy/images.json` (step 10). `--images FILE` reads a JSON object of
    role to digest instead. A refused input exits 2 and names its reason.
    Worked when: `bin/daily`'s JSON output names the `snapshot_hash`, the
    `sheet_hashes` and a nonzero `runs` count per island. A repeated day
    reuses its first window and issues nothing new.

21. **Operator.** Execute each run the day created:

    ```sh
    ZAI_API_KEY=<in the environment> bin/run-agent --run-id <uuid> \
      --profile profile.json --endpoint <chat-completions URL> \
      --processor-dir <dir> [--revision REV] \
      --storage-host H --storage-port P --storage-server-name N \
      --in-process-tools \
      --model-service-host H --model-service-port P \
      --model-service-server-name N --ca-file ca.pem \
      --orchestrator-cert c.pem --orchestrator-key c.key \
      --tools-cert t.pem --tools-key t.key
    ```

    Produces: the run's transcript, terminal row and settlement.
    Worked when: it exits 0 and the run's terminal row is committed; a run
    whose snapshot storage does not hold, or that already ended, exits 2
    before anything is sent.
    List the day's run ids, one per line in slot order, for a shell loop
    over `bin/run-agent`:

    ```sh
    bin/bindings --runs YYYY-MM-DD --state DAILY
    ```

    Start the model service `bin/run-agent` connects to first: the `models`
    service of step 11, or natively with
    `python -m research_agent serve-models --config /absolute/path/models.json`
    where the graphics device does not reach a container (#350); an
    admitted client reads `GET /health` on it.
    Without `--in-process-tools`, `--tool-service-host`, `-port` and
    `-server-name` replace the three `--model-service-*` options and the
    run's calls go to the shared tool service's `POST /v1/calls` under the
    orchestrator certificate (`tools/http.py`). Gap: that listener has no
    start command (step 10, #323), so a run uses `--in-process-tools`.

22. **Owner.** Read the digest. `serve-owner` and `serve-rating` (#315)
    serve the owner actions app and the rating app over HTTPS; the rating
    app's configuration names the stored digest (island and batch id) it
    serves and refuses to start without it. Gaps: **no command** builds or
    publishes that digest (`digest/build.py` and
    `digest/publish.py#publish_digest` have no entry point), and
    `web/inspect/app.py` and `web/report/app.py` have no launcher (#73).
    The owner launcher never wires the health monitor, so the owner API's
    `/api/v1/health` answers 503 whatever the stack's state (#351).

    To reach the owner app from away from the host (decision 0030), set the
    profile's `host.public_hostname` to the reserved tunnel domain. The
    owner API admits exactly one browser origin, `host.front_end_origin`:
    if a separate front end calls it, set that field to the front end's
    final origin before launch, then rerun `bin/stack-config` (step 11),
    which rewrites the configs and keeps secrets and certificates.
    Then, with `NGROK_AUTHTOKEN` and `NGROK_DOMAIN` exported from the private
    environment:

    ```sh
    bin/serve-public --provider ngrok --profile /absolute/path/profile.json
    bin/serve-public --stop
    ```

    Worked when: the first command prints the public URL, and that URL
    answers with the owner login page. It refuses a missing token, a domain
    that is not the profile's, and a Caddyfile that routes anything but the
    owner app. The rating app is never published; raters reach it on the
    host or over the owner's private network.

### Watching several runs at once

`bin/panes` (#329) opens runs side by side in tmux splits over
`bin/tail-runs` and `bin/swarm`. It starts its own tmux server
(`tmux -L swarm`, configured by `deploy/swarm.tmux.conf`), so its bindings
reach no other tmux session; the session `swarm` is its only state. STORAGE
is `bin/tail-runs`' six `--storage-*`, `--ca-file` and `--owner-*` options.

```sh
bin/panes live --state DAILY [--day YYYY-MM-DD] [--max 6] [--island X] -- STORAGE
bin/panes replay [--speed 4] RUN_ID... -- STORAGE
bin/panes agent LINEAGE_ID --state DAILY [--day YYYY-MM-DD] -- STORAGE
bin/panes attach
```

`live` opens window `live`: `bin/swarm` as the control pane and one
`bin/tail-runs --run ID` pane per running run, at most `--max`, tiled.
Window `retile` retiles every five seconds: a run's pane closes when it
settles and the next running run takes a pane. The run ids come from
`bin/bindings --runs DAY --state DAILY` (#317). A run counts as running from
its issue until it holds an ending, when `bin/tail-runs --replay` stops
refusing it; the trace holds no separate start instant, so an issued run
not yet started by `bin/run-agent` also gets a pane. `replay` opens one
`--replay ID --speed N` pane per run, all started on the same second.
`agent` opens that lineage's runs of the day: each ended run replayed whole
and a running one followed. `attach` uses `tmux -CC` under iTerm2, so the
panes are native splits that can be dragged; plain tmux elsewhere. Keys,
after the tmux prefix: `R` retile now, `n` and `p` next and previous run,
`X` close the pane.

## What is missing, in one place

| Step | Missing | Owner issue |
| --- | --- | --- |
| 2, 6 | The population rule, and a selection the release contract admits (seed 20260920; 100 and 2000 families) | #66 |
| 9 | The sized application host | #105 |
| 10, 21 | The tool service's start command (`serve-tools`) | #323 |
| 11, 21 | A native-host mode for the model service where the graphics device does not reach a container | #350 |
| 13 | A funding authorization (`funded`, `paid_execution_enabled`) | Gate; see [authorization-status.md](../evidence/funding/authorization-status.md) |
| 14 | The anchor receiver host; backup binding; restore verification | #74 |
| 16 | Recording the RD-22 owner review | #61, #62 |
| 17 | Marking an index study-qualified | #74 |
| 18 | RD-24 assessment readiness command; study activation | #74 |
| 22 | Digest build and publish command; inspector and report app launchers | #73 |
| 22 | The owner health monitor (`/api/v1/health` answers 503) | #351 |

Every step but the owner's host (9) has a command today, with the gaps
above inside steps 14, 16, 17, 18, 21 and 22. The first live batch cannot run
until at least the host (9), the funding gate (13), the anchor and backup
bindings (14), the live qualification (15) and the population rule (#66)
are closed.
