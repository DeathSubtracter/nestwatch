# Nestwatch

Nestwatch is a maternal-health hackathon prototype that brings fragmented health
measurements and pregnancy context into one explainable view for review.

Our initial use case is patients with type 2 diabetes transitioning from GLP-1
treatment into pregnancy. **Maya, our demo patient, and all demo data are synthetic.**

## The Problem

Glucose, blood pressure, wearable, and sleep data are often reviewed separately
from medication, treatment, and pregnancy context. Reviewing each metric on its
own can miss combined changes or obscure gaps in the available data.

Nestwatch brings those signals together so reviewers can see what changed,
which signals changed together, and where the data is insufficient.

## What Nestwatch Does

- **Unified timeline:** combines normalized device data with patient context.
- **Latest measurements:** preserves timestamps, units, and source/device provenance.
- **Observed changes:** compares recent measurements with a patient's reference window.
- **Explainable multisignal status:** returns `normal`, `watch`, or
  `change_to_review`, with contributing signals, persistence, and reasons.
- **24-hour glucose forecast prototype:** returns a synthetic trajectory at
  five-minute intervals.
- **7-day BP-event forecast prototype:** estimates whether a future synthetic
  systolic or diastolic measurement reaches a configured review threshold.
- **Explicit data quality:** reports missing, stale, partial, and
  `insufficient_data` states instead of treating missing data as normal.

## Demo Flow

```text
Health sources → Open Wearables → Nestwatch backend → analysis → patient/clinician dashboard
```

Maya is the synthetic demo patient. The current repository provides the backend
and dashboard API as the integration point for a patient/clinician frontend.

## Signals

- Blood glucose
- Systolic / diastolic blood pressure
- Resting heart rate
- Heart rate variability (SDNN)
- Sleep duration / efficiency, where available
- Skin / body temperature
- Weight
- Gestational age
- Medication timing / treatment context
- Symptoms

## Architecture

- **Open Wearables:** supplies normalized source data from a separate local instance.
- **FastAPI backend:** combines device measurements with Nestwatch-owned patient context.
- **Descriptive analysis:** deterministic observed-change comparisons and transparent
  multisignal rules.
- **Forecasting prototypes:** simple models trained on separate local synthetic datasets.

A frontend can consume the composed dashboard API for patient data, analysis,
forecasts, and availability information.

## Main API

```http
GET /patients/maya/dashboard
```

One response contains patient context, latest measurements, timeline, observed
changes, pattern status, glucose forecast, BP forecast, sleep summary, and data
quality. It preserves synthetic/prototype/validation flags and explains unavailable
sections while returning the remaining data.

Supply `start_date`, `end_date`, `reference_start`, `reference_end`,
`recent_start`, and `recent_end` as ISO dates. Forecasts retain their existing
synthetic-dataset origins.

Explore the rest of the API through [Swagger docs](http://localhost:8001/docs).

Technical references: [Backend & analysis](docs/backend.md) ·
[API & verification](docs/api.md) · [Models & synthetic data](docs/models.md).

## Run Locally

Use **Python 3.11+**. From the repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

The copy command preserves an existing `.env`. Set the Open Wearables API key
and user ID in `backend/.env`; see [backend setup](docs/backend.md#backend-development)
for configuration details.

Run Open Wearables separately at `http://localhost:8000`, then start Nestwatch
from `backend/` with the virtual environment active:

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Nestwatch runs on **port 8001**. Open [Swagger docs](http://localhost:8001/docs)
to try the dashboard and other endpoints.

Run tests from `backend/`:

```sh
python -m pytest -q
```

Open Wearables requests are mocked in tests; a running upstream server is not required.

## Prototype & Safety

- All demo patients and data are synthetic.
- Forecasting models are hackathon research prototypes, **not clinically validated**.
  Evaluation results describe synthetic-data performance only.
- Nestwatch provides no diagnosis or treatment recommendation.
- Pattern statuses use engineering rules, not clinical cutoffs or a maternal risk
  score. `normal` is a rule status, not a medical assessment.
- The BP forecast concerns a synthetic measurement event, not a diagnosed condition.

## Hackathon

Built for the **2026 UC Berkeley Innovation Intelligence Hackathon**.
