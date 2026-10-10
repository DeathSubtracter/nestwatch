# Developer knowledge and safe workflows

[Project overview](../README.md) · [Backend rules](backend.md) · [API contracts](api.md) · [Synthetic models](models.md) · [Condition-model design](condition-models.md)

Nestwatch currently implements a FastAPI backend, descriptive analysis and two
synthetic forecasting prototypes. Future HDP/GDM/sPTB models are research/design
only. This guide identifies knowledge needed before changing each component;
it supplements the existing documentation rather than redefining its behavior.

## Knowledge by component

Paths in this table are relative to `backend/app/`, unless stated otherwise.

| Component / files | Knowledge needed | Understand before changing |
| --- | --- | --- |
| FastAPI: [main.py](../backend/app/main.py), [dependencies.py](../backend/app/dependencies.py), [routes](../backend/app/routes/patients.py), [schemas](../backend/app/schemas/dashboard.py) | Python 3.11+, type hints, async/await, FastAPI dependencies/lifespan, Pydantic, HTTP status codes, pytest/HTTP mocking | The shared HTTP client is lifecycle-managed; query validation precedes service calls. Schemas are the frontend contract. Optional dashboard failures and nullable fields are deliberate. |
| Settings: [config.py](../backend/app/config.py), [environment template](../backend/.env.example) | pydantic-settings, environment precedence, secret handling | Keep API credentials private; engineering rules and BP demo thresholds have different purposes. Restart after configuration changes. Do not replace a user's `.env` with the template. |
| Open Wearables: [client](../backend/app/clients/open_wearables.py) | httpx, REST, authentication headers, cursor pagination, timeouts and provenance | Configured user ID/key, all-page fetches and separate upstream errors are intentional. Keep Open Wearables external on 8000 and Nestwatch on 8001; do not edit the sibling project. |
| Timeline/Maya: [timeline.py](../backend/app/services/timeline.py), [fixture](../backend/app/fixtures/maya.json), [patient schema](../backend/app/schemas/patient.py) | Health-data units, timezone-aware dates, gestational dating, device versus clinical observations | Preserve original timestamps/source/device and unknown metadata. Sleep is timestamped at session end. Context snapshots are range-specific. Maya has pre-existing type 2 diabetes; she is not GDM-eligible. |
| Observed change: [observed_change.py](../backend/app/services/observed_change.py) | Descriptive statistics, sample means/counts, ratio scales, missingness and provenance | UTC windows do not overlap; freshness is relative to each window end. Mixed units block comparison; Celsius/Fahrenheit percentages are suppressed. Missing/stale data never implies normal. No diagnosis is calculated. |
| Pattern detector: [pattern_status.py](../backend/app/services/pattern_status.py) | Deterministic rules, normalization, signal direction, persistence, correlated measurements and coverage | Thresholds are engineering fixtures. BP components and sleep metrics share group votes. HRV/sleep decreases have different direction from BP/glucose increases. Temperatures are context only. Preserve missing-data abstention and concurrent persistence. |
| Synthetic CGM: [synthetic_cgm.py](../backend/app/services/synthetic_cgm.py) | Python CSV/argparse, local seeded RNGs, daily structure and sampling cadence | Seed/date/5-minute cadence and labels underpin reproducibility. Activity behavior is illustrative, not measured physiology or a binary activity feature. Default CLI output replaces the committed dataset. |
| Glucose forecast: [glucose_forecast.py](../backend/app/services/glucose_forecast.py), [schema](../backend/app/schemas/glucose_forecast.py) | NumPy, scikit-learn pipelines, Ridge/L2 regularization, time-series lags/rolling statistics, cyclic features, MAE/RMSE | All features precede origin. Predict 288 values directly; purge training targets that reach holdout. Scaling is train-only; frozen evaluation precedes final inference refit. Current CSV has no meal/activity event columns. |
| Synthetic BP: [synthetic_bp.py](../backend/app/services/synthetic_bp.py) | Seeded generation, fixed cadence, gradual fixture episodes and outcome-window construction | Two readings/day and deliberately generated episodes are software fixtures. Episode annotations must never enter model features. Changing the generator changes labels/evaluation; perfect performance is not a generation goal. |
| BP forecast: [bp_forecast.py](../backend/app/services/bp_forecast.py), [schema](../backend/app/schemas/bp_forecast.py) | Logistic regression, scaling, supervised event labels, chronological purging, class imbalance, discrimination/calibration metrics | The target is any future synthetic threshold measurement, not HDP. OR/equality and seven-day boundaries matter. Incomplete targets are not negatives; training needs both classes. Report constant-baseline performance and undefined metrics honestly. |
| Dashboard: [dashboard.py](../backend/app/services/dashboard.py), [route](../backend/app/routes/patients.py) | Async composition, threadpool CPU work, dependency isolation, stable JSON contracts | Shared wearable data is reused; analysis windows can differ from timeline range. Forecast origins come from separate CSVs. Unavailable resources differ from successful empty data; retain patient context and available sections. |
| Future conditions: [design](condition-models.md), [datasets](datasets.md) | Pregnancy/obstetric and diabetes domain expertise, supervised learning, biostatistics, eligibility/label adjudication, competing outcomes, missing-data methods, grouped/site/time validation | Actual later outcomes are required. Prior diabetes excludes GDM. sPTB is about labour/PPROM etiology, not delivery mode. Never reuse synthetic events or detector statuses as clinical labels. Obtain review before implementation. |

**NumPy and scikit-learn are current dependencies.** CSV loading uses Python's
standard library; pandas is not currently installed or required. Pandas may help
future authorized cohort audits, but should be proposed separately rather than
added for documentation. EHG work would additionally require signal processing
and WFDB knowledge; it is not interchangeable with the existing wearable metrics.

Docker/Compose knowledge may be useful for managing an externally deployed Open
Wearables instance and its ports/credentials. Nestwatch itself currently has no
Docker deployment. Do not add or alter one as part of routine model work.

## Reading order for a new teammate

1. Read the [README](../README.md) and the [dashboard contract](api.md#mayas-dashboard).
2. Follow the client → timeline → observed change / pattern detector → dashboard
   service path. Read the corresponding schemas and mocked tests under
   `backend/tests/` before changing a contract.
3. Read [synthetic model methodology](models.md) before modifying either generator
   or forecast. The clinical story and synthetic CSVs are separate inputs.
4. Read [dataset evidence](datasets.md) and [condition design](condition-models.md)
   before proposing real-data training. A measurement forecast, a descriptive
   status and a diagnosis-outcome model are different tasks.

## Safest synthetic-data regeneration workflow

The following commands are for a **future deliberate regeneration**, not a
required setup step. Run from the repository root with the existing environment:

```sh
cd backend
source .venv/bin/activate
python -m app.services.synthetic_cgm --output /tmp/nestwatch_cgm_check.csv
python -m app.services.synthetic_bp --output /tmp/nestwatch_bp_check.csv
cmp /tmp/nestwatch_cgm_check.csv app/data/maya_synthetic_cgm.csv
cmp /tmp/nestwatch_bp_check.csv app/data/maya_synthetic_bp_training.csv
```

With unchanged defaults, `cmp` should report no difference. Writing to `/tmp`
first avoids replacing input files used by the running demo. Keep the generator
seed, start date, cadence and synthetic/not-validated fields unless a reviewed
change intentionally updates the fixture. The existing default datasets have
8,640 CGM rows and 730 BP rows; their details are in [models.md](models.md).

If a generator change is intentional, inspect the alternate CSV and run the
relevant existing tests. Review the dataset diff and documented performance
before deliberately replacing a committed input. Never copy real cohort data
over Maya's synthetic CSVs or remove synthetic labeling to make a demo appear real.

## Safest training/evaluation workflow for current models

There is **no standalone training CLI or saved model artifact** for the existing
forecasts. `get_glucose_forecast()` and `get_bp_forecast()` load the CSVs, evaluate
chronologically, refit for inference and cache results in process memory. Calling
the forecast endpoints, or tests that exercise these functions, can train them.
Running a service module with `python -m` is not a training command.

After an intentional model/data change, run targeted checks from `backend/`:

```sh
python -m pytest -q tests/test_synthetic_cgm.py tests/test_glucose_forecast.py tests/test_bp_forecast.py
```

These checks perform synthetic generation/training and protect cadence, leakage,
scaling, target boundaries, determinism, both-class behavior and output contracts.
Broaden to `python -m pytest -q` after implementation changes that affect shared
services. Test upstream requests are mocked. Do not run retraining simply to edit
documentation; this research task made no training or dataset changes.

Restart the backend to clear caches after replacing CSVs or changing code. BP's
cache is keyed by the configured threshold pair; thresholds redefine its event
labels and evaluation. With the backend running, deliberate inference checks are:

```sh
curl --fail-with-body http://localhost:8001/patients/maya/forecast/glucose
curl --fail-with-body http://localhost:8001/patients/maya/forecast/bp
```

These requests need no Open Wearables credentials, but may train lazily on first
use. Synthetic holdout metrics must remain labeled synthetic-data-only. A larger
synthetic sample or more overlapping windows does not create more independent
patients or establish real-world accuracy.

## Before working with real pregnancy data

Read the [training gates](condition-models.md#training-and-validation-gates).
Clinical/domain review is required to distinguish baseline disease from future
diagnosis and spontaneous from indicated delivery. Keep a release dictionary and
feature/label/time specification alongside a versioned split manifest and model
card. Use permitted secure storage for controlled data; do not commit participant
records, source credentials or restricted data to this public demo repository.

For longitudinal data, understand both patient grouping and temporal order:
calendar chronology cannot replace grouping, and a within-patient row split can
leak history. Scaling, imputation, feature selection, weighting/oversampling and
calibration belong inside development folds. Class weighting is not proof of
calibration; compare with natural-prevalence baselines and keep the test set
untouched. Patient-level resampling should determine uncertainty.

For GDM, verify fasting status, assay versus CGM source, screening completion,
diagnostic protocol and diabetes eligibility. For sPTB, verify cervical-length
units/method and labour/PPROM timing. Weeks-and-days fields are not decimal weeks;
gestational dating uncertainty matters. For HDP, BP at/after diagnosis must not
be represented as a prospective predictor of that same diagnosis.

## What not to change casually

- Outcome definitions, forecast horizons/origins, eligibility and assay units.
- Chronological target purging, mother/pregnancy grouping or train-only scaling.
- Seeds/cadence, synthetic flags, prototype flags or `validated=false`.
- Engineering pattern thresholds under the assumption that they are clinical rules.
- GDM eligibility to accommodate Maya, or generic prematurity labels to claim sPTB.
- Dashboard response shapes, explicit null/reason fields or provenance retention.
- The external Open Wearables repository or a teammate's credentials/configuration.

Changing any of these needs a concrete rationale, the relevant existing checks,
updated documentation and review of the actual resulting behavior. No automatic
commit, data-access application or disease-model implementation is part of this task.
