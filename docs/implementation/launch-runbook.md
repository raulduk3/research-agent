# Launch runbook: from merged develop to the first live batch

Written 2026-09-23 for #312 against `develop` as of the 2026-09-23 day
branch. One numbered sequence, in the order the specification and the code
require. Every command named here exists in `bin/`, in `deploy/` or in
`python -m research_agent`; where a step has no command, the step says so and
cites the issue that owns the gap. Nothing in this file has been run as a
whole; it is the path, not evidence that the path works.

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
   embedding views`. A refusal means the batch is not used in step 6.
   Record the measured agreement under
   [remote-embedding.md#Recorded agreement](remote-embedding.md).

6. **Operator.** Build the acquisition-pilot and initial-fit releases:

   ```sh
   bin/build-corpus run --state CORPUS --dsn "$CORPUS_DSN" \
     --population-rule "<rule from #66>" \
     --representation-hash <sha256 of the pinned embedding manifest> \
     --purpose initial_fit --candidates candidates.json \
     --embeddings ./vectors --text ./text [--model-cache-dir DIR]
   bin/build-corpus report --state CORPUS --dsn "$CORPUS_DSN" \
     --population-rule "<rule from #66>" --representation-hash <sha256>
   ```

   Repeat with `--purpose acquisition_pilot` for the pilot release.
   Produces: a committed `label` job whose summary names
   `release_artifact_hash` and the coverage report hash.
   Worked when: the report lists both hashes and the coverage report shows
   `features_complete` for the rows the batch covered.
   Gaps: `candidates.json` is assembled by hand; no command builds it from a
   pilot run. `bin/build-corpus run` enqueues a release only in a schema
   that has none, so the two releases `bin/fit-heads` needs cannot both be
   built into one schema through the CLI today
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

8. **Operator.** Activate the bundle. **No command exists.**
   `models/registry.py#activate_bundle` is reached only through
   `orchestration/weekly.py#run_week` and `artifacts/lineage.py`, neither of
   which has an entry point. Until one exists, the heads fitted in step 7
   serve nothing. The agent-to-digest path owns the gap (#73).

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

10. **Operator.** Build the image. **No command exists.** The `Dockerfile`
    at the repository root builds the one application image
    (`docker build .`, or `docker compose build` against the root
    `compose.yaml`); its entry point, `python -m research_agent`, serves only
    `migrate`, `check-schema`, `collection-readiness` and `serve-storage`.
    No role other than storage has a start command, and nothing records the
    built digest for `bin/daily --image`. Owned by #74.

11. **Owner, then operator.** Bring up storage with its secrets and
    certificates. Two Compose files exist and they disagree:

    - `compose.yaml` (root) is the one that runs: pinned
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
    - `deploy/compose.yaml` declares all nine roles, their networks,
      ceilings and health checks, but every image digest is a placeholder of
      zeros and it declares no secrets. It is the inventory
      `platform.compose` checks, not something `docker compose up` can
      start.

    The owner creates the secret files and the TLS certificate authority;
    no command issues certificates. Then:

    ```sh
    export RESEARCH_AGENT_STORAGE_DSN=<migrator DSN, from the environment>
    uv run --locked python -m research_agent migrate
    uv run --locked python -m research_agent check-schema
    docker compose -f compose.yaml up -d
    ```

    Worked when: `check-schema` prints `Storage schema is current.` and
    both services report healthy. Never run the storage service as the
    migrator identity.
    Gap: the application and migrator roles
    (`storage/roles.py#provision_storage_roles`) are provisioned only inside
    `bin/check-collection-linux` and `bin/probe-storage-mtls`, on disposable
    databases. No command provisions them on the launch database (#74).

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
    No command binds, writes to or verifies either; restore and anchor
    checks are #74's acceptance.

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

16. **Operator, owner review.** The RD-22 Jev smoke test. **No command
    exists.** `measurement/jev.py#select_smoke_sample` and
    `#smoke_test_rubric` build the report and `#check_smoke_activation`
    refuses activation without an owner review, but nothing runs them. The
    live rubric run in
    [jev-smoke-2026-09-23.md](../evidence/models/jev-smoke-2026-09-23.md) is
    provider evidence, not the RD-22 smoke. Owned by #61 and #62; the report
    belongs under `docs/evidence/models/`.

17. **Gate.** Retrieval qualification (MD-12, RD-28): the fixed
    100-paper, 500-question evaluation with two independent reviewer
    judgments per question. The reviewer plan is
    [retrieval-qualification-reviewers.md](../evidence/reviewer-operations/retrieval-qualification-reviewers.md).
    **No command exists** to score it:
    `measurement/retrieval.py#reference_rank_evaluation` is a pure function
    with no entry point, and `publish_index` never marks an index
    study-qualified. No open issue owns the command; #74 consumes the
    evidence.

## 6. SR-17 activation

18. **Owner.** Admit each layer. `platform/readiness.py#evaluate_admission`
    decides one layer against a registered baseline and a comparison report
    whose registration precedes its execution; decision 0024 admits the Jev
    layer (`jev_admitted`), and the future prediction heads stay denied
    whatever is passed. **No command exists**: nothing calls
    `evaluate_admission` or stores its `LayerAdmission`, and
    `assessments/readiness.py#check_assessment_readiness` (RD-24) has no
    entry point either. Study activation as a whole is #74.

## 7. The first day

19. **Owner.** Seed the population: twelve founder configurations, four per
    island (decision 0017), checked by
    `agents/configuration.py#validate_seeded_population`. **No command
    exists** (there is no `bin/seed-population`). The owner's seed action
    (`storage/actions.py`, the actions app) admits a genome only from an
    existing template, so it cannot place the founders. Without them every
    island has no active genome and `bin/daily` issues no run. Owned by #73.

20. **Operator.** Issue the day:

    ```sh
    bin/daily --state DAILY --dsn "$DSN" --profile profile.json \
      --agent-model-manifest <sha256> \
      --image storage=<sha256> [--image ROLE=<sha256> ...] \
      --index-identity <sha256> [--since YYYY-MM-DD] [--device cuda|mps|cpu]
    ```

    `--since` is required on the first day only. Produces: the day's
    listings, acquired papers, cards, sealed sheets and snapshot, each
    island's coverage draw and one run record per sampled paper and active
    genome, and `DAILY/watermark.json`. It starts no run.
    Worked when: its JSON output names the `snapshot_hash`, the
    `sheet_hashes` and a nonzero `runs` count per island. A repeated day
    reuses its first window and issues nothing new.
    Gaps: no command prints the `--agent-model-manifest` hash (only
    `validate_sha256` checks it), the `--image` digests (step 10), or the
    `--index-identity` hash (`bin/import-embeddings` prints counts, not an
    identity). Each is #73's.

21. **Operator.** Execute each run the day created:

    ```sh
    ZAI_API_KEY=<in the environment> bin/run-agent --run-id <uuid> \
      --profile profile.json --endpoint <chat-completions URL> \
      --processor-dir <dir> [--revision REV] \
      --storage-host H --storage-port P --storage-server-name N \
      --model-service-host H --model-service-port P \
      --model-service-server-name N --ca-file ca.pem \
      --orchestrator-cert c.pem --orchestrator-key c.key \
      --tools-cert t.pem --tools-key t.key
    ```

    Produces: the run's transcript, terminal row and settlement.
    Worked when: it exits 0 and the run's terminal row is committed; a run
    whose snapshot storage does not hold, or that already ended, exits 2
    before anything is sent.
    Gaps: the run ids come only from the day's storage (`bin/daily` prints a
    count, not the ids), and no command lists them. The model service
    `bin/run-agent` connects to has no launcher: `models/service.py#create_model_server`
    and `platform/model_service.py#serve_models` exist, but nothing starts
    them. Both are #73's.

22. **Owner.** Read the digest. **No command exists.** `digest/build.py`
    and `digest/publish.py#publish_digest` build and publish it, and
    `web/app.py`, `web/actions/app.py`, `web/inspect/app.py` and
    `web/report/app.py` each define `create_app`, but none has a launcher,
    so the rating app and the owner's paper page are not served. Owned by
    #73.

## What is missing, in one place

| Step | Missing | Owner issue |
| --- | --- | --- |
| 6 | Building `candidates.json`; two releases in one schema | #66 |
| 8 | Bundle activation command | #73 |
| 10 | Image build and digest record; start commands for non-storage roles | #74 |
| 11 | Launch-database role provisioning; real digests in `deploy/compose.yaml` | #74 |
| 14 | Backup and anchor binding and verification | #74 |
| 16 | RD-22 Jev smoke command | #61, #62 |
| 17 | Retrieval qualification scoring command | none open; #74 consumes it |
| 18 | SR-17 and RD-24 admission command | #74 |
| 19 | Founder population seeding | #73 |
| 20, 21 | Manifest, image and index identity hashes; run id listing; model service launcher | #73 |
| 22 | Digest and web app launchers | #73 |

Steps 2 to 7, 12, 15, 20 and 21 have commands today. The first live batch
cannot run until at least steps 8, 10, 11, 13 (funded), 15, 19 and the model
service launcher of step 21 are closed.
