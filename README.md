# Nestwatch

Nestwatch is a hackathon prototype for multimodal maternal-health monitoring during pregnancy transitions.

Our initial use case focuses on patients with type 2 diabetes entering pregnancy after GLP-1 treatment.

## What Nestwatch Does

Nestwatch has two core jobs:

1. Bring health measurements from multiple devices and sources into one maternal-health timeline.
2. Analyze those combined measurements to surface explainable changes that may be useful for patient and clinician review.

## Prototype Architecture

Wearables / health sources
→ Open Wearables
→ Nestwatch backend
→ Nestwatch analysis
→ Patient / clinician frontend

For the hackathon, we use synthetic health data rather than real patient data.

## Planned Inputs

Examples include:

- Glucose
- Blood pressure
- Resting heart rate
- HRV
- Sleep
- Activity
- Weight
- Temperature
- Gestational age
- Medication timing
- Symptoms

The final input set will depend on available synthetic data and the requirements of each analytical output.

## Planned Outputs

The prototype explores:

- Observed changes compared with a patient's previous measurements
- A prototype 24-hour glucose forecast
- A prototype 7-day blood-pressure event forecast
- Explicit insufficient-data states when required measurements are unavailable

## Clinical Boundary

Nestwatch is a hackathon concept prototype.

It does not provide a medical diagnosis, treatment recommendation, or clinically validated prediction.

All demo patient data is synthetic.

## Development Status

Work in progress for the 2026 Innovation Intelligence Hackathon at UC Berkeley.

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

## Verify the Open Wearables integration

Set `OPEN_WEARABLES_BASE_URL=http://localhost:8000`, a valid
`OPEN_WEARABLES_API_KEY`, and the corresponding `OPEN_WEARABLES_USER_ID` in
`backend/.env`. Restart Nestwatch after editing configuration. Keep Open
Wearables running separately on port 8000 and Nestwatch on port 8001.

With Nestwatch started using the command above, run these requests. Choose a
date range containing your seeded data:

```sh
curl --get 'http://localhost:8001/debug/open-wearables/timeseries' \
  --data-urlencode 'start_date=2026-10-01' \
  --data-urlencode 'end_date=2026-10-07' \
  --data-urlencode 'types=blood_glucose' \
  --data-urlencode 'types=heart_rate'

curl --get 'http://localhost:8001/debug/open-wearables/sleep' \
  --data-urlencode 'start_date=2026-10-01' \
  --data-urlencode 'end_date=2026-10-07'
```

Both endpoints require ISO dates (`YYYY-MM-DD`); the range includes both boundary
days. Repeat `types` to select multiple timeseries metrics, or omit it to request
all types. Sleep sessions do not accept a metric filter in Open Wearables.

The client sends `X-Open-Wearables-API-Key`, uses the configured user ID, and
retrieves all pages by following `pagination.next_cursor` while `has_more` is
true. Timeseries requests use `start_time`/`end_time` and `resolution=raw`;
sleep requests use `start_date`/`end_date`.

Responses contain `{"data": [...], "count": N}`. Records retain their original
fields and timestamp strings, including timeseries `type`, `value`, `unit`, and
nested `source.provider`, `source.source`, `source.device`, and
`source.device_type`. Sleep records retain session times, durations, and source
metadata. No records in the selected range returns `{"data": [], "count": 0}`.

Missing credentials or a connection failure returns JSON with status 503;
timeouts return 504. Upstream HTTP errors, invalid responses, and invalid or
repeating pagination cursors return 502. Upstream HTTP errors identify the
upstream status without forwarding its response body. Invalid dates or a
reversed range return 422. HTTP connections are reused and closed at shutdown;
requests have a 10-second timeout, with a 5-second connection timeout.

## Maya's profile and unified timeline

Maya's Nestwatch-owned context is in `backend/app/fixtures/maya.json`. It contains
her fictional patient ID, name, synthetic flag, gestational-age reference,
GLP-1 last-dose date, medication transition, diabetes context, treatment text,
and dated symptoms. The fixture is independent of Open Wearables.

For manual verification:

1. Keep Open Wearables running on `http://localhost:8000`.
2. In `backend/.env`, set a valid `OPEN_WEARABLES_API_KEY` and
   `OPEN_WEARABLES_USER_ID`, with `OPEN_WEARABLES_BASE_URL=http://localhost:8000`
   and `NESTWATCH_PATIENT_ID=maya`. This demo associates Maya with that configured
   Open Wearables user; only Maya is exposed by the patient routes.
3. From the repository root, start or restart Nestwatch:

   ```sh
   cd backend
   source .venv/bin/activate
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

4. In another terminal, request the local profile:

   ```sh
   curl --fail-with-body 'http://localhost:8001/patients/maya'
   ```

   Expect `patient_id: "maya"`, `display_name: "Maya"`, `synthetic: true`, and
   gestational age of 10 weeks, 0 days **as of 2026-10-01**, plus medication,
   diabetes, treatment, and symptom context. This request makes no upstream call.

5. Request the timeline. This example includes all fixture medication and
   symptom events; adjust the range to match your seeded wearable data:

   ```sh
   curl --fail-with-body --get 'http://localhost:8001/patients/maya/timeline' \
     --data-urlencode 'start_date=2026-09-15' \
     --data-urlencode 'end_date=2026-10-07'
   ```

The timeline returns `patient_id`, `synthetic`, `start_date`, `end_date`,
`timezone`, the complete `patient_context` fixture, a sorted `entries` list,
and `count`. The synthetic flag identifies the fictional patient; device
records are fetched from the configured upstream user and are never invented.
Each entry has these fields:

| Field | Meaning |
| --- | --- |
| `timestamp` | Original device timestamp; sleep summaries use session end |
| `kind` | `measurement`, `sleep`, `context`, `medication`, or `symptom` |
| `origin` | `open_wearables` or `nestwatch` |
| `metric_type`, `metric_definition` | Stable metric key and readable definition |
| `value`, `unit` | Original measurement value/unit; structured sleep or pregnancy values have a null unit |
| `provider`, `source`, `device`, `device_type` | Flattened device provenance; missing metadata stays null |
| `details` | Complete original device record or synthetic context metadata |

Device measurements include glucose, systolic/diastolic blood pressure, heart
rate, resting heart rate, SDNN HRV, skin/body temperature, and weight. Sleep
summary values retain source-reported session duration, sleep duration, time
in bed, efficiency, stages, and nap status; the complete session remains in
`details`. No sleep measurements are calculated from device samples.

Dates include both boundary days in UTC. Entries are filtered by their timestamp
and sorted by the actual instant, preserving original device timestamp strings.
Offset-less upstream timestamps are treated as UTC. Sleep sessions are included
when their end timestamp falls in the range, with start/end times retained in
`details`.

Ongoing pregnancy, diabetes, and treatment context appears once as a range
snapshot, marked by `details.snapshot`. Gestational age advances from the fixed
reference date using calendar-day arithmetic; this demo labels weeks before 14
as first trimester, weeks 14–27 as second, and weeks 28 onward as third.
Treatment is only included after its effective transition date. Date-only
medication events use midnight UTC and carry `details.date_only: true`;
symptoms retain their dated reports. Only entries are range-filtered;
`patient_context` always contains the complete fixture and its dated reference.

Empty wearable results still return the available synthetic context. Upstream
failures return the same 502/503/504 errors as the debug endpoints, rather than a
partial-success timeline. Malformed device records return 502; missing, invalid,
or reversed query dates return 422. The patient tests use mocked upstream
responses and require no live Open Wearables server.

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

## Synthetic CGM-style dataset

The local forecasting-prototype dataset is
`backend/app/data/maya_synthetic_cgm.csv`: **8,640 samples** spaced exactly five
minutes apart over 30 complete UTC days. It starts at `2026-09-15T00:00:00Z`
and ends at `2026-10-14T23:55:00Z`, with glucose values in `mg/dL`.

Every row explicitly contains `synthetic=true`, `clinically_validated=false`,
`source=nestwatch_synthetic_cgm`, and the generator seed (`42` by default).
This is a stylized hackathon dataset, not clinically validated physiology.
It does not model disease outcomes or responses to Maya's medication/pregnancy
context. The generator adds smooth daily baseline variation, overnight behavior,
three meal-related rises with gradual returns, small correlated noise, and an
optional illustrative afternoon activity effect. The 80–220 mg/dL bounds are
generator parameters, not clinical classifications.

Regenerate the committed dataset from `backend` with the virtual environment
activated; no Open Wearables server or API credentials are required:

```sh
python -m app.services.synthetic_cgm
```

Defaults use the fixed seed, date, duration, and enabled activity. To write an
activity-disabled variant to a separate file:

```sh
python -m app.services.synthetic_cgm --no-activity --output /tmp/maya_cgm_no_activity.csv
```

The CLI also accepts `--seed`, `--days`, and `--start-date YYYY-MM-DD`. Local RNGs
keep generation deterministic without changing Python's global random state.
Generation does not automatically load the CSV into Open Wearables or the
existing patient timeline. The glucose forecasting prototype below reads the
CSV directly.

Inspect the header and first five samples from the repository root:

```sh
head -n 6 backend/app/data/maya_synthetic_cgm.csv
```

The generator tests verify determinism, five-minute spacing, the exact sample
count, complete numeric/finite values, synthetic labels, daily structure,
optional activity, and reproduction of the saved CSV.

## Prototype 24-hour glucose forecast

`GET /patients/maya/forecast/glucose` trains and runs an interpretable direct
multi-output Ridge regression on the local synthetic CGM CSV. Every response
contains `prototype=true`, `synthetic=true`, and `validated=false`. This is a
hackathon research prototype, not a clinically validated prediction system.
Holdout metrics describe performance on this synthetic dataset only.

The model uses a `StandardScaler` followed by `Ridge(alpha=10, solver="cholesky")`.
There are 19 features in the current CSV:

- Glucose lags at 5, 10, 15, 30, 60, 120, and 1,440 minutes.
- Trailing glucose means and population standard deviations over 60, 180, and
  1,440 minutes.
- Sine/cosine time-of-day features for the daily cycle and its second/third
  harmonics, computed in UTC.

If CSV columns named `meal_indicator` or `activity_indicator` are present, the
loader accepts binary values and adds the last observed indicator plus its
trailing 60-minute fraction. The current CSV has neither event column.
`activity_enabled` is generator metadata and is not treated as an activity
event. No future event values or generator meal schedules are used as features.

Every feature uses samples strictly before its forecast origin. The Ridge model
predicts all 288 future values directly from one origin's feature vector;
inference does not read actual glucose from inside the forecast horizon.

Evaluation splits raw observations chronologically: the first 80% (24 days,
September 15–October 8, 2026) supplies training data; the final 20% (6 days,
October 9–14) is held out. Training examples have one day of preceding history
and a complete 24-hour target **ending before the split**. This gives 6,337
training trajectories. Scaling is fitted only on training features. The fixed
regularization parameter is not selected using holdout results.

The frozen evaluation model predicts six nonoverlapping 24-hour trajectories,
covering 1,728 held-out points. At each later evaluation origin, previously
observed holdout glucose may enter the lag/rolling features; observations at or
after that origin never do. MAE/RMSE measure full-day trajectories rather than
teacher-forced five-minute predictions. After evaluation, a separate fit of the
same fixed model uses all available pre-origin history for the endpoint forecast.
Reported holdout metrics belong to the frozen evaluation model, not this refit.

On the saved seed-42 dataset, synthetic holdout MAE is **7.911949 mg/dL** and
RMSE is **10.018074 mg/dL**. These scores are not evidence of clinical accuracy
or performance on real CGM data.

For manual verification, from the repository root:

```sh
cd backend
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

In another terminal:

```sh
curl --fail-with-body 'http://localhost:8001/patients/maya/forecast/glucose' \
  --output /tmp/nestwatch_glucose_forecast.json
python3 -m json.tool /tmp/nestwatch_glucose_forecast.json
```

Expect `forecast_origin: "2026-10-15T00:00:00Z"`, `horizon_hours: 24`,
`cadence_minutes: 5`, `model_type: "ridge_regression"`, the explicit prototype
flags, 288 `forecast_points`, and `holdout_metrics` labeled
`scope: "synthetic_data_only"`. Each point contains `timestamp` and
`glucose_mg_dl`; model features and chronological evaluation dates/counts are
also returned.

The origin is the **first unobserved timestamp**, five minutes after the last
CSV observation. Points cover `[origin, origin + 24 hours)` at five-minute
cadence: midnight through 23:55 on October 15 for the saved dataset. The origin
comes from the dataset, not the current clock. This endpoint requires no live
Open Wearables server or API credentials.

Training/evaluation runs lazily on the first request and the response is cached
in memory. Restart Nestwatch after regenerating or replacing the CSV. Missing,
invalid, gapped, or insufficient data returns a clear JSON 503 response. No
model files or database are written. Tests cover deterministic training,
strictly past-only features and historical inference, chronological target
boundaries, train-only scaling, finite predictions, and the complete endpoint.

## Prototype seven-day BP measurement-event forecast

`GET /patients/maya/forecast/bp` estimates only this target:

> Whether at least one future synthetic blood-pressure measurement reaches a
> configurable BP review threshold within the next 7 days.

A positive label means **systolic >= configured systolic value OR diastolic >=
configured diastolic value** in at least one paired measurement. Equality
counts. This is a synthetic measurement event, not a maternal risk score or a
prediction of preeclampsia, gestational hypertension, or another diagnosed
condition. All outputs have `synthetic=true`, `validated=false`, and
`prototype=true`.

Training data is the separate local file
`backend/app/data/maya_synthetic_bp_training.csv`: 730 paired measurements at
08:00/20:00 UTC over 365 days (October 15, 2025–October 14, 2026), generated with
seed 73. Every row carries synthetic/not-clinically-validated flags and
`source=nestwatch_synthetic_bp_training`. It is a stylized training fixture,
not Maya's actual history or clinically validated physiology. Most measurements
are baseline periods (456 of 730 in the seed-73 fixture), with seven deliberately
generated BP-rise episodes starting at dataset days 28, 76, 128, 182, 236, 298,
and 337. Strengths vary with the seed. Smooth cosine ramps rise over 6–10 days,
plateau for 2–3 days, and return over 8–10 days, on top of varying baseline levels,
daily offsets, and noise. Several episodes cross the 140/90 review values over
multiple days; weaker episodes need not cross. These episodes are deliberately
generated **software/model testing fixtures, not validated physiology**, and
model no disease outcomes. Their fixed schedule and varied shapes were defined
before inspecting model scores; neither the generator nor logistic parameters
were tuned to obtain perfect performance.

`fixture_episode_id` and `fixture_episode_phase` annotate the CSV for inspection.
The model never uses these annotations, the episode schedule, or future episode
information as features. Positive labels continue to come only from future
measured systolic/diastolic values and the configured thresholds.
It is independent of Open Wearables ingestion and the existing patient timeline.
Regenerate it from `backend`, with the virtual environment activated:

```sh
python -m app.services.synthetic_bp
```

The model uses `StandardScaler` and fixed L2 logistic regression (`C=1`,
`solver=lbfgs`). Eight BP-only features describe the preceding seven days:
systolic/diastolic means, slopes in mmHg/day, population standard deviations,
and latest values. Features use only measurements strictly before the origin.
The response includes raw `feature_values` and the three largest signed
standardized model log-odds terms in `main_contributing_features`; these are
statistical model components, not causal or clinical explanations.

The chronological 80/20 split uses the first 584 measurements (292 days) for
training and the final 146 (73 days) for holdout. Training has one origin per
day, and only complete seven-day target windows ending before the split are
included (279 training examples). Scaling uses training features only. The
frozen evaluation model is scored on 10 nonoverlapping seven-day windows,
covering 140 held-out measurements. The final six holdout measurements cannot
form another complete target and are not scored as a negative event. Earlier
holdout readings may supply features at later origins, never future readings.
After evaluation, the same fixed model is refitted on complete labeled windows
from all available pre-origin history for inference.

At the default 140/90 demo values, training contains **58 positive and 221
negative forecast windows**. The holdout contains **4 positive and 6 negative
nonoverlapping seven-day windows**. Synthetic holdout results at the unchanged
0.5 classification threshold are:

| Metric | Logistic regression | Constant no-event baseline |
| --- | --- | --- |
| Accuracy | 0.700000 | 0.600000 |
| Precision | 0.666667 | Undefined (no positive predictions) |
| Recall / sensitivity | 0.500000 | 0.000000 |
| Specificity | 0.833333 | 1.000000 |
| F1 | 0.571429 | 0.000000 |
| Brier score | 0.222020 | 0.400000 |
| Log loss | 0.756310 | 14.417461 |
| ROC-AUC | 0.916667 | 0.500000 |

The model's confusion counts are TP=2, FP=1, TN=5, FN=2. The constant baseline
always predicts probability 0, so its confusion counts are TP=0, FP=0, TN=6,
FN=4. Log loss uses the scoring library's machine-precision clipping for exact
0/1 probabilities. Undefined metric ratios return null with
`unavailable_reasons`; ROC-AUC remains null with an explicit reason if a changed
threshold produces a single-class holdout.

The API reports all these metrics, confusion/class counts, scoring dates,
`constant_no_event_baseline`, and `scope=synthetic_data_only`. The existing
`no_event_baseline_accuracy` field is retained. These ten deliberately generated
fixture windows form a small software test set, not evidence of clinical
accuracy or generalization to real BP data. Metrics change with review values.

For manual verification, set these editable **demo review values**, not
diagnostic recommendations, in `backend/.env`:

```dotenv
BP_REVIEW_SYSTOLIC_THRESHOLD=140
BP_REVIEW_DIASTOLIC_THRESHOLD=90
```

From the repository root, start or restart Nestwatch:

```sh
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

In another terminal:

```sh
curl --fail-with-body 'http://localhost:8001/patients/maya/forecast/bp' \
  --output /tmp/nestwatch_bp_forecast.json
python3 -m json.tool /tmp/nestwatch_bp_forecast.json
```

Expect origin `2026-10-15T08:00:00Z`, `horizon_days=7`,
`model_type=logistic_regression`, a probability in [0, 1],
`status=forecast_available`, the event definition/thresholds, prototype flags,
feature values, and synthetic holdout metrics. The origin is the first unknown
measurement time; the event interval is `[origin, origin + 7 days)`, with the
exclusive end `2026-10-22T08:00:00Z`. It is based on the fixed dataset, not the
current clock. No live Open Wearables server or credentials are required.

`status` reports data/model availability, not a low/high or normal/abnormal
classification. Insufficient recent history, incomplete training/holdout windows,
stale history, or a single training label class returns `status=insufficient_data`,
`probability=null`, and explicit `reasons`. It never substitutes probability 0.
For example, changing the demo review values to 200/150 and restarting yields
single-class insufficiency on this dataset. Invalid/nonpositive configuration
fails at startup. Missing, invalid, or gapped dataset files return JSON 503.

Training is lazy and cached by the threshold pair; changing thresholds changes
labels, metrics, and inference, rather than reusing a differently defined model.
Restart after replacing the CSV to clear any response cached from the older
dataset. Tests verify dataset reproducibility, gradual episode shapes, both
classes in training and holdout, exact target boundaries/equality/OR logic,
chronological target purging, train-only scaling, future-data isolation,
exclusion of fixture annotations from features, classification/baseline metric
calculations, probability bounds, configuration, insufficiency, and the real
CSV-to-endpoint path. No dashboard endpoint is added.
