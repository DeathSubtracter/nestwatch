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
