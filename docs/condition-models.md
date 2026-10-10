# Future condition-specific models: research and design

[Dataset evidence](datasets.md) · [Developer guide](developer-notes.md) · [Current models](models.md)

**Status: design only, 2026-10-10. No HDP, GDM or spontaneous-preterm-birth
model exists in Nestwatch. No disease coefficients, probabilities or endpoints
have been created.** Existing forecasts remain synthetic, prototype and
not clinically validated. Approval of a dataset/target is required before coding
a condition model; this document is a proposal, not a training result.

## Recommended first model

Start with a **small first-trimester HDP logistic-regression baseline using
nuMoM2b**, after authorized access and release-level label/timing verification.
Its clinical BP and pregnancy outcome collection fits Nestwatch's existing BP
pipeline more closely than EHG-only preterm datasets. The first version should
predict a later pregnancy outcome, not a seven-day disease event.
[nuMoM2b evidence and access constraints](datasets.md#1-numom2b).

This is conditional: the team does not currently hold the data, and DASH's
platform migration makes hackathon access uncertain. If access cannot be secured,
continue the existing descriptive/synthetic demo. Open PhysioNet GDM/EHG data
can support limited offline feasibility work, but their timing, selection and
event-count limitations do not justify a disease-probability dashboard.

## What Nestwatch already has

| Current component | Available information | Limit for condition modeling |
| --- | --- | --- |
| Open Wearables client / unified timeline | Glucose, systolic/diastolic BP, HR/resting HR, SDNN HRV, skin/body temperature, weight; source-reported sleep fields where present | Availability is user/provider-dependent; no diagnosis labels or clinical follow-up; no activity metric is currently ingested |
| Maya fixture | Dated gestational age, pre-existing type 2 diabetes, last GLP-1 dose/transition, treatment text, dated symptoms | Fictional context; no age, height/BMI, parity, cervical length or delivery outcomes |
| Observed-change service | Window means/counts/change, freshness, units and provenance | Descriptive, not disease labels or trained predictors |
| Multisignal detector | Relative changes, directional contributions, persistence and coverage | Engineering rules; its statuses are not HDP/GDM/sPTB labels |
| Glucose / BP forecasts | Local synthetic trajectories / future threshold-measurement events | No real pregnancies or disease outcomes; cannot be relabeled as condition models |
| Dashboard API | Composed current responses with explicit unavailable/insufficient sections | No condition-model framework; its current contract must stay unchanged |

See [backend analysis](backend.md), [API contracts](api.md) and [synthetic models](models.md)
for existing behavior. Mapping source measurements into a timeline does not
establish that a trained model can use them interchangeably with clinic assays.

## HDP plan

| Decision | Proposed approach |
| --- | --- |
| Population | Initially nulliparous singleton pregnancies matching nuMoM2b; no prevalent HDP at origin. Exclude chronic hypertension from this first incident-GH/PE target; a superimposed-preeclampsia model needs a separate cohort/definition. Diabetes may be a baseline covariate only if represented and adequately evaluated. |
| Target | Subsequent adjudicated gestational hypertension or preeclampsia/eclampsia during the index pregnancy, after the first-trimester origin and before delivery. Preserve subtype labels; do not use a BP threshold crossing as a diagnosis. |
| Origin / horizon | First study visit at 6+0–13+6 weeks; remainder of pregnancy to delivery. Verify the origin precedes the recorded outcome. A fixed 7/28-day horizon is deferred until onset times and complete follow-up are confirmed. |
| Initial features | A small audited set: clinic BP summary available at origin, gestational age, age, measured BMI and prepregnancy diabetes/history. Source-confirmed sleep/activity questionnaires may be assessed later, separately from wearable HRV/sleep. |
| Longitudinal extension | BP average, slope, maximum and variability from strictly pre-origin dated readings, with observation count and span. A slope needs multiple time points; within-visit replicates are not a longitudinal trend. Add weight/glucose/resting HR/HRV/sleep only when the labeled cohort actually has comparable prenatal measurements. |
| Missing data | Required eligibility/outcome/timing fields are not imputed. Training-only imputation and missingness indicators for supported optional covariates; no zero-filled BP, no invented trajectories. Abstain when required source/units/history are unavailable. |
| Split | Patient/mother-grouped development folds; held-out site and, when dates allow, later-enrollment test cohort. Keep all visits from a pregnancy together. ALSPAC is a possible later external test after target and population harmonization. |
| Leakage risks | Diagnostic or post-onset BP/proteinuria, treatment initiated after diagnosis, delivery/postpartum fields, final HDP labels in predictors, and future visit measurements at an earlier origin. Onset unknown means no fixed near-term target. |
| Imbalance | Estimate event counts after eligibility filtering. Begin unweighted penalized logistic regression; consider class weights only inside training folds with validation calibration. Test on the natural event prevalence. |
| Baseline / candidate | Training-prevalence predictor and a small L2 logistic model. Consider shallow gradient-boosted trees only if event counts support the additional parameters and untouched evaluation improves. No neural network recommendation. |
| Evaluation | ROC-AUC, PR-AUC, Brier score/log loss, calibration plot/intercept/slope, sensitivity, specificity, PPV/NPV and confidence intervals at a validation-selected operating point. Accuracy alone is insufficient. |
| Explainability | Report fitted coefficients in meaningful source units and per-feature log-odds contributions, coverage and uncertainty. Associations are not causal or treatment instructions. |

Maya's type 2 diabetes alone does not establish HDP-model eligibility: parity,
hypertension history, baseline clinical fields and population transportability
would still need verification.

## GDM plan

**Eligible only without pre-existing type 1 or type 2 diabetes and without GDM
already diagnosed at origin. Maya is ineligible.** A future demo would need a
separate eligible patient; this task adds no patient or eligibility code.

| Decision | Proposed approach |
| --- | --- |
| Dataset choice | Prefer an authorized nuMoM2b first-visit/later-GDM cohort; NICHD FGS is an alternative if early assays and later labels are released. PhysioNet visceral-adipose data are accessible for feasibility, not a verified incident-GDM training set. HAPO's OGTT-derived label cannot establish a pre-OGTT CGM forecast. |
| Target | First later clinician/assay-confirmed GDM diagnosis in the index pregnancy under the dataset's documented diagnostic protocol. Store diagnosis time and protocol; do not substitute type 2 diabetes or generic hyperglycemia. |
| Origin / horizon | First-trimester/pre-diagnosis assessment to subsequent pregnancy screening/diagnosis, commonly around 24–28 weeks where documented. This is a gestational landmark endpoint, not a promised fixed number of days. |
| Initial features | Only audited pre-origin age, BMI/weight, gestational age, family history, and supported history/activity/sleep fields. Prior GDM is relevant in a parous cohort; it cannot be learned from a nulliparous cohort as though broadly represented. |
| Intended future signals | Prediagnosis fasting/overnight glucose, CGM mean/variability/post-meal summaries, weight gain, activity and sleep. Require timestamped CGM and meal/activity metadata before claiming these features. No suitable released prediagnosis CGM cohort was confirmed in this review. |
| Missing data | Unknown pre-existing-diabetes status or diagnosis timing causes exclusion/abstention. Training-fold imputation for optional supported covariates; no imputed labels or synthetic CGM to fill a real cohort. Record screening completion and follow-up; an unscreened patient is not automatically a negative. |
| Split | Mother/pregnancy-grouped development; reserve site/later-enrollment test where possible. For a tiny exploratory cohort, grouped resampling can quantify instability but cannot supply a credible external test. A nested case-control assay study needs sampling corrections/full-cohort validation for absolute probability. |
| Leakage risks | The OGTT values defining the label, glucose after diagnosis, diabetes treatment, delivery mode/birth weight, future gestational weight gain, postpartum diabetes and selective screening. First fasting glucose may already have established GDM. |
| Imbalance | Check eligible events before selecting feature count. Small public cohorts do not gain information through oversampling. If weights are used, fit within training folds and evaluate/recalibrate at true prevalence. |
| Baseline / candidate | Prevalence-only and small penalized logistic regression with clinical covariates. A tree model is an optional later comparison for a sufficiently large audited cohort, not the default. No neural networks. |
| Evaluation | PR-AUC/ROC-AUC, Brier/log loss, calibration and confidence intervals; sensitivity, specificity and PPV/NPV at a documented validation operating point. Report screening/label ascertainment and subgroup performance. |
| Explainability | Coefficients/contributions from the actual fitted model and missingness coverage; report laboratory versus interstitial-CGM source differences. Never invent coefficients from the literature or apply a general-diabetes model to GDM. |

The open GDM CSV lacks diagnosis dates and has only 18 positive records before
eligibility auditing. A compact association benchmark might eventually be
possible, but future diagnosis and stable calibration are not established.
[Dataset audit](datasets.md#5-physionet-visceral-adipose-tissue-during-pregnancy).

## Spontaneous preterm birth plan

| Decision | Proposed approach |
| --- | --- |
| Population / data | Ongoing singleton pregnancies at a fixed antenatal landmark. Prefer nuMoM2b for a nulliparous design, or authorized PREDS when prior-preterm history is needed. Do not pool multifetal pregnancies or selected EHG cohorts into the same model without a distinct target/population analysis. |
| Target | Delivery before **37+0 weeks** initiated by spontaneous labour or PPROM, using adjudicated etiology. Medically indicated preterm delivery is not a positive sPTB label. Induction/Caesarean mode alone does not establish etiology; PPROM may precede induction. |
| Origin / horizon | After visit-2 cervical assessment (16+0–21+6 weeks) in nuMoM2b, or the approximately 24-week PREDS visit, to 37+0 weeks. A fixed 7/14-day model requires separate onset/delivery timing, adequate near-term event counts and evaluation. |
| Initial features | Pre-origin cervical length with method/time, gestational age, parity/obstetric history, prior sPTB/PPROM when represented, and supported baseline demographics. PREDS fetal fibronectin/symptoms may be assessed only if available before origin. |
| Intended optional signals | Resting HR/HRV, sleep, activity, temperature, weight, BP and glucose only from an outcome-labeled cohort with comparable timed measurements. Current wearable data alone cannot supply sPTB labels; EHG is an additional sensor modality, not an available Nestwatch metric. |
| Missing data | Missing delivery etiology, dating or follow-up is not negative. Require the primary cervical/history inputs for a model trained with them; a cervical-length-free version would need separate training/evaluation. Optional-covariate imputation must be fitted within training folds. |
| Competing outcomes | Record indicated preterm birth separately. For an observed-outcome binary baseline it is a documented non-sPTB outcome, not a healthy/normal label; report it separately. A dynamic future-window model should explicitly model competing delivery/censoring, e.g. discrete-time competing-event logistic hazards, before claiming cumulative event probabilities. |
| Split | Group all pregnancies from a mother and all segments/channels/visits from one pregnancy. Prefer held-out site/time and independent-cohort evaluation. TPEHGT's 26 pregnancy recordings are only 18 pregnancies; establish the mapping before splitting. |
| Leakage risks | Birth gestational age, delivery reason, labor already in progress, later cervical/fibronectin measurements, neonatal fields, label-bearing filenames and segment-level splits. TPEHG's ≤37 versus <37 documentation needs boundary audit. |
| Imbalance | Use actual pregnancy event counts, not recording/segment counts. Keep validation/test prevalence intact; training-only weighting may be compared. Selected EHG term/preterm groups cannot establish general-population calibration. |
| Baseline / candidate | Prevalence and prespecified cervical/history logistic regression. Shallow trees only after adequate events and external validation justify complexity. EHG studies need a separate signal-processing research track; no neural networks proposed. |
| Evaluation | PR-AUC/ROC-AUC, calibration, Brier/log loss, sensitivity/specificity/PPV/NPV with patient-level intervals; report spontaneous versus indicated counts and subgroup results. Use censoring-aware horizon metrics for a future-window extension. |
| Explainability | Source-unit cervical/history coefficients and per-feature contributions; show time of measurement and absent inputs. Explanations are associations, not diagnosis or recommended interventions. |

## New clinical fields that would be needed

These are design requirements, **not additions to the current schemas**.

| Category | Proposed fields / metadata |
| --- | --- |
| Identity and dating | Research mother ID, pregnancy ID, site/cohort, singleton/multiple status, index date, estimated delivery date/dating method, gestational weeks+days at each observation; predictor collection and availability times |
| Maternal history | Age, height, prepregnancy weight/BMI, gravidity/parity, prior HDP/preeclampsia, chronic hypertension, diabetes type/status/onset, prior GDM, prior sPTB/PPROM and gestational ages, family diabetes/hypertension history |
| Clinical measurements | BP method/cuff/posture/clinic versus home, paired SBP/DBP and times; lab glucose fasting status/assay/units, OGTT protocol/date/results; HbA1c when dataset-supported; cervical length in mm with ultrasound method/date; fetal fibronectin only when selected/available |
| Context / treatment | Structured medication name/class/dose/start/stop and indication; relevant obstetric interventions and timestamped symptoms/contractions/rupture-of-membranes information; no inference of medical diagnoses from free text alone |
| Outcomes / eligibility | Diagnosis and onset dates, criterion/protocol/source, delivery date and gestational age, spontaneous-labour/PPROM/indicated etiology, indication, loss to follow-up, censoring and outcome ascertainment through each horizon |
| Optional wearable enrichment | Timestamped source-specific activity, sleep coverage/nap status, HRV definition, CGM versus lab/device glucose, wear time and missingness; no undocumented substitution between measurements |

## Training and validation gates

1. Obtain lawful access and the actual versioned dictionary; select one cohort,
   population, target and landmark. Obtain user review before implementation.
2. Audit labels and time ordering with obstetric/diabetes expertise. Resolve
   protocol differences and distinguish absent, unknown, untreated and ineligible.
3. Count independent pregnancies/events after exclusions. Plan sample size and
   predictor parameters with a biostatistician; do not use a fixed events-per-variable
   slogan as proof of adequacy. [Sample-size methods](https://www.bmj.com/content/368/bmj.m441).
4. Freeze grouped development/validation/test assignments before model selection.
   Use later-enrollment/site holdout when available. If dates are suppressed,
   report grouped/site evaluation as such; never invent a chronological split
   from row order or participant IDs.
5. Fit imputation, scaling, feature selection, weighting and optional calibration
   within development folds. Keep every feature strictly before origin and purge
   overlapping outcome windows. Preserve test-set prevalence and report unknown
   outcomes/censoring instead of fabricating negatives.
6. Compare a prevalence baseline and a small logistic model. Evaluate calibration,
   discrimination, uncertainty, population subgroups and out-of-distribution
   behavior. An all-negative baseline's accuracy is not evidence of usefulness.
7. Preserve dataset hash/version, feature/label specifications, exclusions,
   preprocessing/model parameters, split manifest, code version and evaluation
   provenance. Follow [TRIPOD+AI reporting](https://www.bmj.com/content/385/bmj-2023-078378).
8. An offline fit may be called trained only with these recorded artifacts.
   Internal validation is not external or clinical validation. Independent real
   cohorts, calibration/transport assessment and prospective clinical evaluation
   would be needed before claims of clinical utility.

## Future implementation boundary

A future offline workflow would have separate cohort adapters, eligibility
checks, landmark/label construction, train-only preprocessing, grouped evaluation
and versioned artifacts. It should reuse verified normalization/provenance where
appropriate, not treat pattern contributions or synthetic BP event labels as
disease outcomes. There is no need to introduce an abstract model framework now.

No current API gains condition fields in this task. When approved work eventually
reaches an API, untrained/ineligible/insufficient states must be explicit; never
emit arbitrary probabilities, substitute zero for an unavailable model, or set
`validated=true` merely because a model fits. Do not silently change synthetic
demo flags when experimenting with real data. Review an API version/contract and
data provenance separately from the current Maya dashboard.
