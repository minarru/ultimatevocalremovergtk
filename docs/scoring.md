# Scoring saved model and ensemble outputs

`uvr score` evaluates separated audio against known references. It does not load
models or run inference. Use `uvr separate` or `uvr ensemble` on the prepared
mixtures, then map their saved outputs explicitly. Scoring needs no installed
weights and does not guess identities or stems from filenames.

## Quick workflow

```bash
# Optional: add BSS Eval v4 support to the existing UVR environment.
.venv/bin/python -m pip install -r requirements-score.txt

# Prepare references. Output directories must not already exist.
./uvr score prepare --sources sources.json -o prepared

# Quick single-stem check using only existing NumPy and SoundFile dependencies.
./uvr score files --reference vocals=reference.wav \
  --estimate vocals=estimated.wav --metrics basic -o single-score

# Evaluate explicitly mapped saved outputs; default metrics=all includes BSS Eval.
./uvr score run --dataset prepared/dataset.json \
  --estimates estimates.json -o scores --report jsonl

# Compare two reports, with B minus A deltas.
./uvr score compare scores-a/results.json scores-b/results.json -o comparison

# Compare a model and an ensemble contained in the same report.
./uvr score compare scores/results.json scores/results.json \
  --a-candidate model-one --b-candidate ensemble-b
```

`--metrics basic` computes waveform SDR, SI-SDR and silent-target residual RMS.
`--metrics all` adds BSS Eval and requires the optional dependency file. This
backend has been validated with Python 3.14. Missing or incompatible museval gives
an installation message before batch scoring starts. `uvr bench` is unchanged.

For `files`, repeat `--reference STEM=PATH` and `--estimate STEM=PATH` for a group.
The default `--group pair` contains `vocals` and `instrumental`; `--group four`
contains `vocals`, `drums`, `bass`, and `other`. `--group custom` permits other
explicit stem names with basic metrics only. `--candidate`, `--label`, `--kind
model|ensemble`, `--song-id`, and optional `--provenance RUN_MANIFEST` identify a
single-file candidate. The defaults are `files`, `files`, `model`, and `file`.

## Source manifests and preparation

A native source manifest has this format. Relative paths are resolved against the
manifest's own directory; absolute paths are also accepted.

```json
{
  "schema_version": 1,
  "kind": "uvr.score.sources",
  "songs": [
    {
      "id": "song-001",
      "title": "Example",
      "artist": "Artist",
      "split": "core",
      "sources": [
        {"stem": "vocals", "path": "song-001/lead.flac"},
        {"stem": "vocals", "path": "song-001/backing.flac"},
        {"stem": "piano", "path": "song-001/piano.flac"}
      ]
    }
  ]
}
```

The converted MoisesDB `selected-flac/manifest.json` is also accepted directly.
The importer uses its track paths and source categories, retains track IDs, and
preserves its 12 `core` / four `holdout` song assignments. It does not read the
original per-song `data.json` paths, which still name WAV files.
Use repeatable `--song SONG_ID` or `--split core` / `--split holdout` to select a
subset. Omitted native split labels become `unspecified`.

Our preparation convention, recorded as `moises-uvr-v1`, is:

| Source category | Four-stem reference | Vocal/instrumental reference |
| --- | --- | --- |
| All `vocals` sources, including backing vocals | vocals | vocals |
| `bass` | bass | instrumental |
| `drums` and `percussion` | drums | instrumental |
| Every remaining category | other | instrumental |

Every source is assigned once within each group. Duplicate source paths are
rejected. Stereo and sample rate are preserved; unequal source lengths or sample
rates fail the song. Sources are summed in float64 and exported as 32-bit float
WAV. Both groups use the same mixture and one shared attenuation gain, applied
only when a mixture or reference exceeds 0.99 peak. Stems are never normalized
independently. Exported references must reconstruct the mixture within an
absolute tolerance of `5e-7`, allowing float32 rounding.

`dataset.json` records the mapping, split, gain, source hashes and exact mixture
and reference paths with hashes, dimensions and silence labels. Song directories
have generated safe names; song identity comes from the manifest. Absent sources
remain labelled silent references. For example, “Gloria’s Swan Song” has useful
vocal/instrumental references but no bass or drums. Those absent stems do not
receive artificial perfect four-stem scores.

## Estimates manifests

Each candidate has a stable ID, display label, kind, and explicit song/group/stem
mapping. IDs are user supplied: they do not need to resolve to installed models.
Change the candidate ID when changing settings you want to compare. A run
manifest can supply provenance, including available UVR settings, but does not
replace the explicit output mapping.

```json
{
  "schema_version": 1,
  "kind": "uvr.score.estimates",
  "candidates": [
    {
      "id": "model-one",
      "label": "Model One, GPU autocast",
      "kind": "model",
      "provenance": "saved-run/run.json",
      "estimates": [
        {
          "song_id": "song-001",
          "group": "pair",
          "stems": {
            "vocals": "saved-run/song-vocals.wav",
            "instrumental": "saved-run/song-instrumental.wav"
          }
        }
      ]
    },
    {
      "id": "ensemble-b",
      "label": "Ensemble B",
      "kind": "ensemble",
      "estimates": [
        {
          "song_id": "song-001",
          "group": "pair",
          "stems": {"vocals": "ensemble/song-vocals.wav"}
        }
      ]
    }
  ]
}
```

Remove `provenance` when no run manifest is available. Relative estimate and
provenance paths resolve against the estimates manifest. Duplicate candidate IDs,
duplicate song/group entries, unknown songs/groups and unmapped stems are errors.
A candidate may supply a single stem; no complementary estimate is synthesized.

## Metric definitions and limits

| Metric | Protocol | Interpretation |
| --- | --- | --- |
| `waveform_sdr` | `10 log10(sum(reference²) / sum((estimate-reference)²))`, whole track | Higher is better; gain, stereo, timing and reconstruction changes count as error. |
| `si_sdr` | Remove each channel's mean, project estimate onto reference using one shared gain across channels, then compare projected target and residual energy | Higher is better; global gain changes are ignored, changes to stereo balance are retained. |
| `bss_sdr` | museval BSS Eval v4 stereo image SDR | Higher is better under the BSS distortion model. |
| `bss_sir` | BSS Eval interference ratio | Higher generally indicates less interference from other reference sources. |
| `bss_sar` | BSS Eval artifacts ratio | Higher generally indicates fewer artifacts under the decomposition. |
| `bss_isr` | BSS Eval spatial distortion ratio | Higher generally indicates less spatial distortion. |
| `silent_target_rms_dbfs` | Estimated output RMS where target reference RMS is below −80 dBFS | Lower indicates less output during target silence. |

Basic metrics use bounded audio blocks and float64 accumulation. Stereo channels
are not independently gain fitted. The scorer rejects empty or non-finite audio,
sample-rate differences, channel-count differences and length differences. It
never aligns, resamples, pads, truncates or changes loudness. Supply the complete
prepared mixture to inference and retain its gain and timeline in the estimates.

BSS Eval uses pinned `museval==0.4.1`, 512-tap filters fitted over the whole track,
one-second windows and hops, stereo image mode, no source permutation, and no
padding. It follows museval's window framing: trailing partial windows are omitted
unless the entire track is shorter than a window. Evaluation is sequential, one
song/candidate/group at a time, on CPU with numerical thread pools limited to one.
It can take considerably longer and use more memory than basic metrics.

The pair and four-stem groups are evaluated separately: overlapping sources such
as instrumental and drums never enter the same BSS call. BSS requires all
references and estimates in its group. An incomplete group, any entirely silent
source, or a backend failure produces an explicit unavailable status. Basic
metrics remain available for valid supplied stems. BSS windows that the backend
cannot evaluate remain individually labelled undefined rather than becoming zero.

A silent target has unavailable SDR/SI-SDR; a constant nonzero reference has
unavailable SI-SDR. Exact matches may give positive infinity. JSON represents
undefined and infinite numbers as `null` plus an explicit `status`, never literal
NaN or Infinity. Finite aggregates exclude these values and report status counts.
This also means a perfect reference control cannot have an ordinary finite delta
against a degraded estimate; comparisons label that pair `nonfinite_pair`.

Silent-target analysis uses one-second windows and includes a final partial
window. Reports retain each silent window's start, duration and residual RMS,
as well as energy-weighted RMS across all selected silent samples. This is a
leakage measurement, not SDR and not a separately normalized listening track.

## Reports, comparisons and interruption

All four commands support `--report human|json|jsonl` and `--quiet`. Human progress
is on stderr and identifies the song, candidate, stem and metric stage. JSON mode
writes one final stdout document. JSONL emits phase events and completed work
counts before its final `finished` event. `--quiet` suppresses progress events in JSONL too. Batch counts refer to song/candidate/
group jobs, not individual seconds or stems. BSS Eval has no internal percentage
callback; its active stage remains visible until the call returns.

Batch scoring writes `results.json` and a long-form `results.csv` table. `files`
also writes both when given `-o`. The JSON contains candidate metadata, audio
hashes, reference group identity, dataset metadata, settings provenance when
provided, metric protocol/backend versions, individual BSS windows, per-song
scores and summaries. Summaries group by candidate, split, target group, stem and
metric. BSS aggregates finite windows to a median within each song first, then
takes the median across songs; long songs do not receive extra weight. Core and
holdout results remain separate.

Comparisons require equal metric protocols and reference identities, including
the preparation mapping. They match song/split/group/stem keys and report B−A
per song (with both original values and statuses), median finite changes, wins/losses/ties (absolute tolerance `1e-9` dB),
unavailable pairs and missing results on either side. Higher is better except
silent-target RMS, where lower is better. With several candidates in a report,
select each candidate explicitly. There is no combined quality score across
interference, artifacts and preservation of musical content.

Outputs use new directories and refuse collisions. JSON/CSV checkpoints are
replaced atomically after each completed group, and prepared songs are published
only after validation. Ctrl-C or SIGTERM retains completed results and marks the
report stopped, with pending jobs listed explicitly. In-progress checkpoints are labelled
`running`. A failed song/group is recorded while other jobs continue.
Checkpoint JSON is authoritative if a forced process kill occurs between the
JSON and CSV updates. Re-run unfinished entries with a new output directory;
automatic resume is not implemented.

Exit codes follow the CLI convention: `0` success, `1` all scoring/preparation
jobs failed, `2` invalid configuration or output collision, `3` partial failure,
`130` interrupted. An unavailable metric is a reported measurement status and
does not by itself make the audio job fail.
