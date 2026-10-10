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