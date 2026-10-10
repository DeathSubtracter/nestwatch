# Backend & analysis

[Project overview](../README.md) · [API reference](api.md) · [Forecasting prototypes](models.md)

Development setup, configuration, and descriptive analysis rules for the
Nestwatch backend. Commands assume the repository root unless stated otherwise.
All analysis thresholds described here are engineering fixtures, not clinical
cutoffs; the prototype is not clinically validated.

## Backend development

Use Python 3.11 or newer. From the Nestwatch repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `backend/.env` does not already exist, copy `backend/.env.example` to
`backend/.env` (run `cp .env.example .env` from `backend`). Configuration reads
that file regardless of the working directory; environment variables take
precedence:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPEN_WEARABLES_BASE_URL` | `http://localhost:8000` | Open Wearables HTTP(S) URL |
| `OPEN_WEARABLES_API_KEY` | Empty | Open Wearables API key, stored as a secret |
| `OPEN_WEARABLES_USER_ID` | Empty | Open Wearables user identifier |
| `NESTWATCH_PATIENT_ID` | `maya` | Nestwatch patient identifier |

Invalid configuration fails at startup. The API key and user identifier can stay
empty for `/health`, which does not contact Open Wearables. The debugging
endpoints require a valid Open Wearables API key and user identifier.

Start Nestwatch from `backend` on its separate port:

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

`GET http://localhost:8001/health` returns `{"status":"healthy"}`.
API documentation is at `http://localhost:8001/docs`.
CORS permits local frontend origins on ports 3000 and 5173 for both `localhost`
and `127.0.0.1`. Unexpected application errors return a generic JSON 500 response
and are logged server-side; FastAPI handles HTTP and request-validation errors.

Run tests from `backend` with the virtual environment activated:

```sh
python -m pytest tests -q
```

`pytest` also works from `backend`. All upstream requests in the tests are
mocked; Open Wearables does not need to be running.

## Observed-change analysis

`GET /patients/maya/observed-change` compares raw measurement sample means
between two configurable windows. It describes the data without diagnosing,
assigning clinical thresholds, creating a risk score, or forecasting.

For manual verification:

1. Keep Open Wearables running on port 8000 and set the existing API key and
   user ID in `backend/.env` to your seeded demo user.
2. Optionally configure these data sufficiency rules in `backend/.env`:

   ```dotenv
   OBSERVED_CHANGE_MIN_SAMPLES=3
   OBSERVED_CHANGE_MAX_STALENESS_DAYS=2
   ```

   The minimum is per metric, per window, and must be at least 2. The staleness
   limit is a nonnegative UTC calendar-date gap between the latest sample and
   **that window's end**, not today's date. Defaults are engineering data
   sufficiency rules, not clinical thresholds. They also apply to weight.
3. Start or restart Nestwatch from the repository root:

   ```sh
   cd backend
   source .venv/bin/activate
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

4. In another terminal, request the comparison. Adjust both windows to match
   your seeded measurements:

   ```sh
   curl --fail-with-body --get 'http://localhost:8001/patients/maya/observed-change' \
     --data-urlencode 'reference_start=2026-10-01' \
     --data-urlencode 'reference_end=2026-10-07' \
     --data-urlencode 'recent_start=2026-10-08' \
     --data-urlencode 'recent_end=2026-10-14'
   ```

All four dates are required and include both boundary days in UTC. Each start
must be on or before its end; the reference window must end before the recent
window starts. Invalid, reversed, or overlapping windows return 422 without
calling Open Wearables.

The response includes the windows, applied `policy`, and eight `metrics` rows:
glucose, systolic/diastolic blood pressure, resting heart rate, SDNN HRV,
skin/body temperature, and weight. Every requested metric is present even when
it has no measurements. Each row contains:

- `metric_type`, `metric_name`, `metric_definition`, and `unit`.
- `reference_sample_count`, `recent_sample_count`, and their respective means.
- `absolute_change`: the signed difference `recent_mean - reference_mean` in
  the original unit. No unit conversion or sample imputation is performed.
- `percent_change`: `absolute_change / reference_mean * 100`, when meaningful.
  It is null for zero/negative baselines, insufficient data, or numeric overflow.
  Temperature percentages are suppressed unless the unit is Kelvin (`K` or
  `kelvin`), because Celsius/Fahrenheit have an arbitrary zero. The reason is
  given in `percent_change_unavailable_reason`.
- Latest sample timestamps and per-window provider/source/device provenance,
  including each source group's sample count. Unknown provenance stays null.
  `provenance_changed` reports a difference in source/device sets between windows.
- `enough_data`, `status` (`compared` or `insufficient_data`), and explicit
  `reasons`, such as `missing_recent_data`, `too_few_reference_samples`,
  `stale_recent_data`, `missing_unit`, or `incompatible_units`.

Means use equally weighted raw samples. Sources sharing the exact same unit are
pooled and their provenance remains visible; measurements are not adjusted for
source differences or sampling cadence. Multiple units in one window prevent
that window's mean. Different units across windows prevent comparison, with
`reference_units`, `recent_units`, and `available_units` retained for inspection.

Missing, sparse, stale, and incompatible-unit data never generate a comparison
or an implied normal result: change fields are null and `enough_data` is false.
Single-unit means from available samples may still be shown alongside those
explicit insufficiency reasons. `compared` only indicates that the configured
data checks passed; no normal/abnormal label is returned.

The service uses the existing unified timeline pipeline for the combined date
range, then includes only device measurement entries in each window. Samples
in gaps between windows, context, symptoms, sleep, and unrequested heart-rate
measurements do not contribute. All cursor pages are included. Pipeline errors
remain 502/503/504 responses instead of being presented as missing measurements.

## Multisignal pattern detector

`GET /patients/maya/pattern-status` uses the same unified Open Wearables timeline
and observed-change comparison helpers. It is a deterministic descriptive
hackathon rule system, not a diagnosis, disease probability, maternal risk score,
or validated medical alert. Every response has `validated=false` and
`prototype=true`. It does not use or modify either predictive model.

For each usable signal, the detector preserves the shared comparison's sample
counts, means, units, freshness checks, and provider/source/device provenance.
The signed normalized change is:

```text
scale = max(reference population standard deviation, abs(reference mean) * 0.05)
normalized_change = (recent mean - reference mean) / scale
```

The relative floor avoids exaggerated contributions from nearly constant
reference data. Both windows use equally weighted raw sample means. These are
**engineering fixtures for hackathon testing, not clinical cutoffs or validated
effect sizes**. Zero/invalid scales are unavailable, not a zero change.

Increases in glucose, systolic/diastolic BP, and resting HR have positive
directional contributions. Decreases in SDNN HRV, source-reported actual sleep
duration, and sleep efficiency have positive contributions. Opposite directions
do not contribute. Sleep duration uses `sleep_duration_seconds` in seconds;
efficiency uses `efficiency_percent`. Missing actual sleep duration is never
replaced by session length or time in bed. Naps are excluded. Multiple non-nap
sessions on one UTC date use their sample mean, not a daily duration total.
Invalid/missing sleep fields are excluded and their counts reported.

A signal must have enough samples, enough distinct sampled UTC days in each
window, compatible units, fresh data, and unchanged source/device sets. Its
whole-window directional change must reach the configured threshold. It must
also reach that same threshold in daily recent means on at least three
consecutive sampled dates, relative to the same reference mean/scale. Missing
dates break runs; a later stable or undersampled date ends an active run. The
run must end within the configured freshness gap of the recent window's end.

The five primary groups are glucose, BP, resting HR, HRV, and sleep. Systolic and
diastolic BP share one vote; sleep duration and efficiency share one vote. The
highest status requires at least three groups qualifying on the same three
consecutive UTC dates near the window's end. This prevents changes at unrelated
times, or multiple measurements of one group, from creating that status.

Skin/body temperatures are optional context only and never vote for escalation.
Their normalization uses reference variability alone because Celsius/Fahrenheit
have an arbitrary zero. Unavailable temperature context is reported separately
and does not reduce primary coverage.

| Status | Rule |
| --- | --- |
| `insufficient_data` | Any required signal is unavailable, or too few primary groups are usable; the detector abstains. |
| `change_to_review` | Enough distinct contributing groups meet the concurrent persistence rule. |
| `watch` | A usable primary signal changed without meeting the highest rule, or optional primary coverage/provenance is incomplete. |
| `normal` | All primary signals are usable with known providers and no qualifying directional change; this only describes these prototype rules. |

Missing, sparse, stale, mixed-unit, or changed-source core signals cannot produce
`normal`. The default required signals are glucose, both BP components, resting
HR, and SDNN HRV. Missing optional sleep reduces `data_quality.coverage` to
`partial`, so otherwise stable data returns `watch`. Unknown providers stay
unknown and also reduce coverage. Coverage can remain partial alongside
`change_to_review` if other usable groups satisfy the rules; the response always
exposes that limitation. No samples are imputed.

The response includes `policy`, `contributing_signals`, `non_contributing_signals`,
all per-signal `comparison` objects, normalized/directional changes, contributions,
daily means, observed/qualifying dates, longest/latest runs, concurrent group
dates, `reasons`, `explanation`, and `data_quality`. A contribution is the positive
directional magnitude after all contribution rules pass, zero for a usable
non-contributor, and null for unavailable data. There is no aggregate numeric
score or probability.

Defaults are in `backend/.env.example`; override these in `backend/.env` and
restart Nestwatch:

| Variable | Default | Prototype purpose |
| --- | --- | --- |
| `PATTERN_NORMALIZED_CHANGE_THRESHOLD` | `1.0` | Minimum directional normalized change, for window and daily means |
| `PATTERN_RELATIVE_SCALE_FLOOR` | `0.05` | Reference-mean fraction for the primary normalization scale floor |
| `PATTERN_MIN_DAYS_PER_WINDOW` | `3` | Minimum distinct sampled UTC dates in each window |
| `PATTERN_MIN_SAMPLES_PER_DAY` | `1` | Minimum recent samples for a qualifying daily mean |
| `PATTERN_PERSISTENCE_DAYS` | `3` | Consecutive days for individual and concurrent persistence |
| `PATTERN_REVIEW_MIN_GROUPS` | `3` | Distinct groups needed for `change_to_review` (minimum 2) |
| `PATTERN_MIN_AVAILABLE_GROUPS` | `3` | Distinct usable primary groups required to avoid abstention |
| `PATTERN_REQUIRED_SIGNALS` | JSON array of the five core metrics above | Required signals; sleep may also be required |
| `OBSERVED_CHANGE_MIN_SAMPLES` | `3` | Shared minimum samples per window |
| `OBSERVED_CHANGE_MAX_STALENESS_DAYS` | `2` | Shared maximum UTC date gap from each window's end |

BP forecasting review thresholds do not affect this detector. All four query
dates are required, inclusive UTC dates; windows must be ordered and must not
overlap. Invalid dates/windows return 422 before any upstream requests. Real
pipeline errors remain 502/503/504 rather than being labeled missing data.

For manual verification, keep Open Wearables on port 8000 and configure the
existing base URL, API key, and user ID in `backend/.env`. From the repository
root, start or restart Nestwatch:

```sh
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

In another terminal, choose windows containing your seeded measurements:

```sh
curl --fail-with-body --get 'http://localhost:8001/patients/maya/pattern-status' \
  --data-urlencode 'reference_start=2026-10-01' \
  --data-urlencode 'reference_end=2026-10-07' \
  --data-urlencode 'recent_start=2026-10-08' \
  --data-urlencode 'recent_end=2026-10-14' \
  --output /tmp/nestwatch_pattern_status.json
python3 -m json.tool /tmp/nestwatch_pattern_status.json
```

Inspect `status`, `validated=false`, `prototype=true`, `data_quality`, and each
signal's comparison/persistence reasons. Sparse existing demo data may correctly
return `insufficient_data`; it is not interpreted as stable or replaced with
forecast training data. The tests mock all upstream data and cover stable,
moderate/persistent, concurrent, directional, sleep, missing/stale/source-changed,
configuration, deterministic, and endpoint error/schema cases.
