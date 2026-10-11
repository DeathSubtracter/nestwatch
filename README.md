# Nestwatch

Multimodal Maternal Monitoring for High-Risk Pregnancies

Bringing fragmented wearable signals, metabolic trends, and clinical context into one transparent, explainable view.

Built for the 2026 UC Berkeley Innovation Intelligence Hackathon.

ACCESS OUR PITCH DECK HERE: https://docs.google.com/presentation/d/11CCSIWzc1HrqlWES2wFEBRf5zlmSB5R3/edit?usp=sharing&ouid=101655455924727037414&rtpof=true&sd=true

DEMO VIDEO: https://youtu.be/sArTKkmU7Lk?si=7BHTMZQFX40vEVhu

Clinician demo portal: https://nestwatchproviderportal.lovable.app/

Our initial use case is patients with type 2 diabetes transitioning from GLP-1
treatment into pregnancy. **Maya, our demo patient, and all demo data are synthetic.**

## The Problem - The "Ozempic Baby" Clinical Crisis

Over 12% of U.S. adults currently take GLP-1 receptor agonists (e.g., semaglutide, tirzepatide), but there is a huge clinical unmet need in addressing consequenes of people who are actively on the drug. A specific need is identified as these therapies restore metabolic balance and ovulation, very recent literature found that healthcare systems are experiencing a sharp increase in unplanned pregnancies ("Ozempic Babies").   Because GLP-1 medications are contraindicated during pregnancy, patients must discontinue treatment immediately. This sudden withdrawal triggers an acute cardiometabolic and glycemic rebound. Observational studies show that patients discontinuing GLP-1s near pregnancy entry face heightened risks of:  
Gestational Diabetes (GDM): 17% vs. 13% baseline   
Hypertensive Disorders of Pregnancy (HDP / Preeclampsia): 46% vs. 36% baseline   
Preterm Delivery (<37 weeks): 20% vs. 15% baseline

Glucose, blood pressure, wearable, and sleep data are often reviewed separately
from medication, treatment, and pregnancy context. Reviewing each metric on its
own can miss combined changes or obscure gaps in the available data.

Nestwatch brings those signals together so reviewers can see what changed,
which signals changed together, and where the data is insufficient.

## What Nestwatch Does
Existing consumer wearables and clinical sensors (CGMs, smartwatches, BP cuffs) capture valuable signals, but they operate in isolated hardware silos. A isolated glucose spike or HRV drop lacks clinical meaning without knowing gestational age or medication history.   Nestwatch acts as a unified software intelligence layer. It pulls multi-modal device streams via open APIs, aligns them with patient-reported context (last GLP-1 dose, gestational week, symptoms), and presents a synchronized, explainable timeline for both patients and Maternal-Fetal Medicine (MFM) care teams.   
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

Nestwatch is designed as a B2B2C Software-as-a-Sensor platform.   
Distribution Channel: Sold directly to OB-GYN and MFM clinical practices.   
Reimbursement Engine: Clinics bill insurance via Remote Patient Monitoring (RPM) CPT codes (e.g., Medi-Cal / CMS coverage for continuous monitoring data transmission and clinical review).   
Unit Economics: Assumes $50 Per Active Patient Per Month (PAPM) SaaS fee over a 6-month high-risk monitoring window ($300 total revenue per patient).   
Market Sizing: Capturing 5% of the ~3.6M annual U.S. births (targeting GLP-1 rebound and high-risk metabolic transitions) represents an initial $54M/year SAM, expanding into a $1.6B+ TAM across all high-risk metabolic pregnancies.   
Post-Hackathon Regulatory Pathway: Pursuing FDA 510(k) / De Novo clearance as Software as a Medical Device (SaMD) through Pre-Submission feedback and prospective validation studies

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

Unified Maternal Timeline: Fuses continuous metabolic, cardiovascular, autonomic, and contextual data.   
Provenance Preserved: Tracks and displays explicit device provenance, measurement units, and exact timestamps.   
Deterministic Observed Change Engine: Compares recent patient-relative windows against early-pregnancy reference baselines.   
Explainable Multisignal Status: Classifies status into normal, watch, or change_to_review with rule-based justifications.   
Synthetic 24-Hour Glucose Forecast: Generates a synthetic 5-minute trajectory prototype.
Synthetic 7-Day Blood Pressure Event Forecast: Estimates the probability of a future synthetic systolic/diastolic threshold breach.   
Data Quality First: Explicitly tracks missing, stale, partial, and insufficient_data states to prevent false confidence

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

## Working With the Models

Model work requires Python, NumPy/scikit-learn, time-series features, grouped and
chronological validation, leakage prevention, evaluation/calibration, and
health-data units/provenance. Pregnancy outcome modeling also requires clinical
and biostatistical expertise.

Read the [developer guide](docs/developer-notes.md) for component prerequisites
and safe regeneration/retraining workflows. Existing [synthetic models](docs/models.md)
remain separate from [future HDP/GDM/sPTB designs](docs/condition-models.md) and
[dataset research](docs/datasets.md). No condition-specific model is implemented;
GDM would apply only without pre-existing diabetes, so Maya is not eligible.

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

**Pitch deck:** [Nestwatch: Refined Pitch and Technical Appendix](https://docs.google.com/presentation/d/11CCSIWzc1HrqlWES2wFEBRf5zlmSB5R3/edit?usp=sharing) (Google Slides) · [PowerPoint copy](pitch/Nestwatch_Refined_Pitch_and_Technical_Appendix.pptx)

**Demo video:** [Watch the prototype walkthrough on YouTube](https://youtu.be/sArTKkmU7Lk)
