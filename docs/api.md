# API reference & verification

[Project overview](../README.md) · [Backend & analysis](backend.md) · [Forecasting prototypes](models.md)

Detailed response contracts and manual verification for the Open Wearables
integration, Maya's timeline, and the composed dashboard. Commands assume the
repository root unless stated otherwise. Keep Open Wearables on port 8000 and
Nestwatch on port 8001. Forecast endpoint details are in [models.md](models.md).

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

## Maya's dashboard

`GET /patients/maya/dashboard` composes the existing backend services into one
response. It adds no analytical rules and does not alter the glucose/BP models.
All six ISO date parameters are required:

- `start_date`, `end_date`: inclusive UTC range for `timeline` and
  `latest_measurements`. Latest means the last measurement **inside that range**,
  selected by timestamp instant, with the original timestamp string retained.
- `reference_start`, `reference_end`, `recent_start`, `recent_end`: the existing
  observed-change/pattern windows. They must be ordered and nonoverlapping but
  need not lie inside the timeline range. `sleep_summary` uses the recent window.

The composer fetches all cursor pages once for each Open Wearables resource over
the combined date range. Shared timeline normalization, context snapshots,
filtering, and comparison helpers are reused. Timeline context is assembled for
its own requested range, so an ongoing pregnancy/treatment snapshot is retained
even when the reference window begins earlier. Existing cached forecast services
run off the request's event loop.

Every response has the same keys, including null unavailable sections:

| Section | Contents |
| --- | --- |
| `patient` | Maya's complete local synthetic context |
| `latest_measurements` | Object keyed by the eight observed-change metric types; each row has value, unit, timestamp, metric definition, provider/source/device/device type, availability status, and reasons |
| `timeline` | Existing frontend-ready timeline object, limited to `start_date`–`end_date` |
| `observed_change` | Existing comparison response unchanged, or null if unavailable |
| `pattern_status` | Existing detector response unchanged, or null if unavailable |
| `glucose_forecast` | Existing synthetic 24-hour forecast response, or null if unavailable |
| `bp_forecast` | Existing synthetic seven-day measurement-event forecast response, including its insufficient-data result when applicable, or null on service failure |
| `sleep_summary` | Recent window, latest source-reported session, session count, status, and reasons |
| `data_quality` | Overall availability, per-section statuses/reasons, per-metric comparison reasons, missing/stale latest metrics, and unavailable sections |

Top-level `synthetic=true`, `prototype=true`, and `validated=false` label this
Maya prototype. All nested patient/analysis/forecast flags are preserved. Device
entries keep `origin=open_wearables` and their original provenance. The dashboard
does not replace missing device measurements with synthetic forecast CSV data.
The forecasts keep their existing dataset-based origins and evaluation metadata;
query dates do **not** re-anchor or retrain them for historical dashboard windows.

Latest measurements and sleep use `available`, `missing`, `stale`, or
`unavailable`. A missing value is null, never zero; stale values remain visible
alongside the stale flag. Freshness reuses `OBSERVED_CHANGE_MAX_STALENESS_DAYS`
(default 2) relative to `end_date` for latest measurements and `recent_end` for
sleep, not the current clock. Sleep is the latest session by end timestamp,
including a nap if that is the latest session; `is_nap` and complete details are
preserved. No duration or efficiency is inferred, and no new sleep aggregation
is calculated.

`data_quality.sections` distinguishes `available`, `partial`, `insufficient_data`,
and `unavailable`. `unavailable_sections` lists both unavailable and
insufficient-data sections with reasons; insufficient analysis results remain in
the response. Detailed existing metric reasons remain available in both the
section metadata and nested analyses. Overall status is `complete` when every
section is available, `partial` when some usable device information remains with
incomplete sections, and `insufficient_data` when latest measurements and both
device analyses are all unavailable/insufficient. Successful synthetic forecasts
do not mask absent device data. These statuses describe availability, not health.

An optional service failure returns HTTP 200 with the remaining sections and
explicit quality information. Sleep failures leave timeseries comparisons
available; timeseries failures leave local patient context, available sleep, and
forecasts available. An unavailable resource is distinguished from a successful
empty response. Unavailable sleep counts are null rather than implying zero
sessions. Unexpected optional failures are logged and return a generic reason;
upstream response bodies are never forwarded. Missing/invalid/reversed dates or
overlapping comparison windows return 422 before any service calls.

For manual verification, keep Open Wearables running on port 8000 and set the
existing base URL, API key, and user ID in `backend/.env`. From the repository
root, start or restart Nestwatch:

```sh
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

In another terminal, choose dates matching your seeded measurements:

```sh
curl --fail-with-body --get 'http://localhost:8001/patients/maya/dashboard' \
  --data-urlencode 'start_date=2026-10-01' \
  --data-urlencode 'end_date=2026-10-14' \
  --data-urlencode 'reference_start=2026-10-01' \
  --data-urlencode 'reference_end=2026-10-07' \
  --data-urlencode 'recent_start=2026-10-08' \
  --data-urlencode 'recent_end=2026-10-14' \
  --output /tmp/nestwatch_dashboard.json
python3 -m json.tool /tmp/nestwatch_dashboard.json
```

Check that all nine section keys are present, each latest measurement retains
its provenance, prototype flags are explicit, and `data_quality.sections` explains
missing/stale/insufficient results. Sparse demo data may correctly produce a
partial or insufficient-data dashboard. Interactive documentation is also at
`http://localhost:8001/docs`. Dashboard tests use mocked Open Wearables transport
and verify full/partial responses, exact parity with existing endpoints,
resource/forecast failure isolation, UTC/latest selection, context snapshots,
pagination reuse, date validation, and a stable nullable response schema.
