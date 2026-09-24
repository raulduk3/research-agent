# Corpus volume write throughput on the development host

Dated 2026-09-24. Issue #338: during the corpus build the development Mac
showed a load average near 268 with about 550% CPU used across ten cores,
the build itself at 7% CPU, and `fskitd` and Spotlight (`mds`,
`mds_stores`) busy on `/Volumes/research-agent`. Document throughput was
about 350 an hour against 500 when the volume is quiet. The load is I/O
wait, not compute. This record measures the volume against the internal
disk and says where the store belongs.

## Setup

- Corpus volume: `/Volumes/research-agent`, an APFS sparse bundle (600 GiB,
  82 GiB used) stored on an ExFAT partition of an external SSD, so every
  write passes through FSKit's user-space path.
- Internal disk: APFS data volume, 926 GiB, 81 GiB free at the time of
  measurement.
- Probe: one Python process per run. Sequential: 512 writes of 1 MiB of
  random bytes, one `fsync` at the end. Random: 2,000 writes of 4 KiB at
  random 4 KiB offsets inside that file, `fsync` after each. The probe file
  is deleted after each run. Plain `fsync` on macOS does not force the
  drive cache (`F_FULLFSYNC`); the same call is used on both sides, so the
  comparison holds even though absolute durability differs.
- Taken at 04:55 while the corpus build was still running; one-minute load
  average 49 to 69, fifteen-minute 150 to 159. The volume numbers therefore
  include contention with the build, which is the condition that matters.

## Result

| Target | Run | Sequential MiB/s | Random 4 KiB fsync writes/s |
| --- | ---: | ---: | ---: |
| Corpus volume | 1 | 508 | 507 |
| Corpus volume | 2 | 525 | 515 |
| Corpus volume | 3 | 531 | 542 |
| Internal disk | 1 (cold) | 580 | 7,793 |
| Internal disk | 2 | 3,269 | 5,524 |
| Internal disk | 3 | 2,554 | 6,448 |

- Sequential writes on the volume hold at about 520 MiB/s, five to six
  times slower than the internal disk once warm. That is ample for large
  source documents written once.
- Small synchronous writes are the gap: about 520 per second on the volume
  against 5,500 to 7,800 on the internal disk, a factor of ten to fifteen.
  That is the pattern of the artifact store (many small files, metadata
  updates, commits), and it is where FSKit's user-space path costs most.

## Where the store belongs

The artifact store (extracted text, labels, vectors, indexes and the
database-adjacent files used in fitting and serving) belongs on the
internal disk; only the large, write-once source documents (original PDFs
and archives) belong on the external volume. The measurement supports the
split the issue proposed.

The constraint is space: the internal disk had 81 GiB free, down from about
215 GiB two days earlier, and the volume already holds 82 GiB. Moving the
artifact store needs a size split of what the 82 GiB is (originals against
derived artifacts) before it is planned. Per #338, the move is its own
issue and is not made here.

## Spotlight

Not yet done. Excluding the volume from Spotlight is the owner's command:

```
sudo mdutil -i off -d /Volumes/research-agent
mdutil -s /Volumes/research-agent
```

The before-and-after document rate still has to be recorded here: the rate
per hour over the hour before the command and over an hour after it, with
the build otherwise unchanged. Until then, the Spotlight share of the
slowdown is unmeasured; `mds` activity during the build suggests it is
real but does not size it.

## What this does not establish

- Not the build's document rate after the Spotlight exclusion.
- Not read throughput, which fitting and serving also depend on.
- Not a quiet-volume baseline: every volume run shared the disk with the
  running build.
