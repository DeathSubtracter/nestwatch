# Synthetic datasets & forecasting prototypes

[Project overview](../README.md) · [Backend & analysis](backend.md) · [API reference](api.md)

Dataset generation, model features, chronological evaluation, and forecast
verification. These are hackathon research prototypes using synthetic data;
reported performance is synthetic-data performance only, not clinical validation.
Commands assume the repository root unless stated otherwise.

Before modifying or regenerating these components, read the
[developer guide](developer-notes.md) for required skills, safe alternate-output
generation, retraining/cache behavior and changes that require review. The default
generator commands below overwrite their dataset files; the guide shows a safer
comparison workflow. Future [condition-model design](condition-models.md) and
[real-dataset research](datasets.md) are separate from these synthetic prototypes;
no HDP, GDM or sPTB model is implemented.

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
CSV-to-endpoint path.
