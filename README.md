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

The API key and user identifier can stay empty for this initial health-only app.
Invalid configuration fails at startup. The health endpoint does not contact
Open Wearables.

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
