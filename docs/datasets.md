# Pregnancy dataset research

[Condition-model design](condition-models.md) · [Developer guide](developer-notes.md) · [Existing synthetic models](models.md)

Research checked **2026-10-10** using official repositories and original study
reports. This is a candidate assessment, not an assertion that Nestwatch has
received access, trained a condition model, or validated one. No applications
were submitted and no restricted participant data were obtained.

## How to read this assessment

**Confirmed** means explicitly described in the cited documentation; **NC** means
not confirmed in the material reviewed, not proof of absence. Study collection
does not guarantee that a variable is in the distributable release. For managed
datasets, verify the release dictionary, patient linkage, time fields, missingness,
and permitted use before writing a training adapter. Population sizes below are
cohort/release sizes, not independent training examples or numbers of outcomes.

## Candidate overview

| Dataset | Population / release | Relevant targets | Hackathon assessment |
| --- | --- | --- | --- |
| nuMoM2b | 10,038 enrolled; DASH document lists 9,289 | HDP, GDM, sPTB | Best broad candidate after access and dictionary audit; access not assured during this hackathon |
| ALSPAC maternal obstetric records | 13,706 women with abstracted records | HDP, GDM; sPTB needs subtype audit | Strong longitudinal BP candidate; managed application and costs make immediate use unlikely |
| HAPO / HAPO-FUS | Original blinded cohort 23,316; NIDDK release lists 4,697 | GDM ascertainment, HDP; sPTB subtype NC | Managed access; OGTT-derived GDM is not automatically a future-diagnosis target |
| NICHD Fetal Growth Studies | 2,334 low-risk singleton participants plus 468 with obesity; separate 171 twin pregnancies | GDM; HDP/sPTB release labels NC | Promising early biomarkers; access inquiry and release verification needed |
| PhysioNet maternal visceral adipose cohort | 154 recruited; 133 released/followed | GDM | Downloadable now; small exploratory cohort with temporal/label limitations |
| MFMU Preterm Prediction Study / PREDS | 3,073 recruited singletons; 2,929 in principal analyses | sPTB | Strong clinical/cervical-length candidate after managed access |
| PhysioNet TPEHG DB 1.0.1 | 300 pregnancies, one recording each | Selected term/preterm outcome | Downloadable; small EHG feasibility benchmark, not a ready Nestwatch sPTB model |
| PhysioNet TPEHGT 1.0.0 | 26 pregnancy recordings from 18 pregnancies; 5 nonpregnant recordings | Spontaneous term/preterm outcome | Downloadable; too small for standalone development; investigate subject mapping first |

Counts, population definitions, access, and the target limitations are supported
by the sources in each profile below. Assessment of hackathon feasibility is our
engineering judgment, not a repository promise of approval or turnaround.

## Documented feature coverage

This table concerns **pregnancy measurements**, not postpartum follow-up.
"No" for the small public datasets means absent from their published field lists.

| Dataset | Cervical length | Glucose / CGM | BP over pregnancy | Maternal weight |
| --- | --- | --- | --- | --- |
| nuMoM2b | Yes in study, visits 2/3; release audit pending | GDM testing documented; prenatal numeric glucose fields need audit; CGM NC | Repeat study visits; not a dense wearable series | BMI/anthropometry documented; release/timing audit |
| ALSPAC | NC | Glycosuria and GDM diagnosis; quantitative antenatal glucose/CGM NC | Repeated antenatal chart measurements | Repeated antenatal measurements |
| HAPO/FUS | NC | Fasting/1h/2h OGTT, HbA1c, C-peptide; CGM NC | OGTT BP and additional chart readings in original study; released longitudinal series NC | Height/weight/BMI at OGTT; prenatal trajectory NC |
| NICHD FGS | NC | Early HbA1c and longitudinal blood biomarkers in studies; actual released assays/CGM NC | NC | Repeated anthropometry documented |
| PhysioNet visceral adipose | No | First fasting glucose; no CGM | Same-day systolic/diastolic means only | Pregestational BMI; raw weight history not released |
| PREDS | Yes, study assessments at 24/28 weeks | NC / CGM NC | NC | Anthropometry/BMI documented; released repeat weight NC |
| TPEHG | No; funneling is not cervical length | Diabetes indicator only; no glucose/CGM | Hypertension indicator only; no BP readings | Single recording-time weight, sometimes missing |
| TPEHGT | No | No glucose/CGM | No BP readings | Recording-time weight, sometimes missing |

| Dataset | HR | HRV | Sleep | Activity | Other confirmed biomarkers / history |
| --- | --- | --- | --- | --- | --- |
| nuMoM2b | NC | NC | Questionnaires; sleep-disordered-breathing substudy, not universal | First-visit self-reported physical activity | Age, BMI, prepregnancy diabetes; cervical length/fetal fibronectin in study; nulliparous population |
| ALSPAC | Prenatal HR NC | Prenatal HRV NC | Prenatal fields NC in reviewed obstetric release | Prenatal fields NC in reviewed obstetric release | Age/BMI, parity, previous hypertension/diabetes, proteinuria, haemoglobin, medication/history records |
| HAPO/FUS | NC | NC | NC | NC | Age, parity, smoking/alcohol, family history of diabetes/hypertension |
| NICHD FGS | NC | NC | NC | NC | Ultrasound biometry, nutrition, blood biomarkers; exact clinical history release NC |
| PhysioNet visceral adipose | No | No | No | No | Age, pregnancies count, prior-DM field, ultrasound visceral-fat thickness, ethnicity |
| PREDS | NC | NC | NC | Work/environment information; wearable activity NC | Prior preterm birth, parity, symptoms, cervical examinations, fetal fibronectin, vaginal infection assessments |
| TPEHG | No reported HR series | No reported HRV | No | No | EHG; age, parity, abortions, smoking, bleeding, diabetes/hypertension indicators |
| TPEHGT | No reported HR series | No reported HRV | No | No | EHG/TOCO contraction annotations; age, parity, abortions, smoking |

EHG is uterine electrical activity, not HRV. Fetal heart rate is not maternal
resting HR. Neither missing signals nor postpartum measures should be represented
as available prenatal inputs. This review did not confirm a released dataset
combining dense prenatal CGM, longitudinal BP, all desired wearable signals, and
appropriately timed labels for all three conditions.

## 1. nuMoM2b

**Official source:** [NICHD study](https://www.nichd.nih.gov/research/supported/Pages/nuMoM2b.aspx),
[DASH study](https://dash.nichd.nih.gov/study/226675),
[public-release document metadata](https://dash.nichd.nih.gov/document/226928).
The release metadata lists 9,289 participants; published enrollment is 10,038.
Do not assume all enrolled participants are present in the requested release.
[Published enrollment description](https://pmc.ncbi.nlm.nih.gov/articles/PMC11496016/).

It is a prospective, diverse US nulliparous singleton cohort. Individual linked
visits occur at 6+0–13+6, 16+0–21+6, 22+0–29+6 weeks and delivery. The study
documents BP/anthropometry and cervical assessments, rather than continuous
home monitoring. [Original methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC4387083/).

Published work confirms gestational hypertension/preeclampsia outcomes,
pregestational diabetes and first-trimester BMI/BP/sleep/activity;
GDM testing and family diabetes history; and sPTB outcomes with serial cervical
length/fetal fibronectin. These studies support candidacy, not confirmation of
every release column. [HDP study](https://www.jacc.org/doi/10.1016/j.jacc.2025.02.015),
[GDM study](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2795756),
[sPTB study](https://jamanetwork.com/journals/jama/fullarticle/2610337).

**Access:** DASH account/request, DUA and approval; IRB approval/exemption is
study-specific. No open redistribution license is established here. DASH currently
announces a platform migration. Confirm request availability, permitted users,
de-identification and onset-date retention. [DASH policies](https://dash.nichd.nih.gov/resource/policies),
[migration notice](https://dash.nichd.nih.gov/).

**Decision:** leading HDP candidate; also GDM/sPTB candidates. Nulliparity limits
transport to women with previous GDM, preeclampsia or preterm birth. An HDP
outcome alone does not establish a seven-day onset label.

## 2. ALSPAC maternal obstetric records

**Official source:** [University of Bristol cohort](https://www.bristol.ac.uk/alspac/index.html),
[variable search](https://variables.alspac.bristol.ac.uk/).
UK recruitment covered 1991–1992 pregnancies. Individual obstetric abstraction
is available for 13,706 women, including dated antenatal measurements, derived
HDP classifications, recorded GDM and obstetric outcomes.
[Cohort profile](https://pmc.ncbi.nlm.nih.gov/articles/PMC3600619/).
Measurement timing follows irregular clinical visits throughout pregnancy,
rather than a fixed wearable cadence.

Repeated BP, weight and urine measurements offer more temporal detail than a
single intake row. Labour onset/induction and delivery details are documented,
but a ready adjudicated sPTB label was not verified. Delivery mode alone is not
sufficient to determine spontaneous onset.
[Obstetric data description](https://pmc.ncbi.nlm.nih.gov/articles/PMC11208852/).

**Access:** online proposal, committee review, agreements and costs; the access
page advertises a proposal response within 10 working days, not data delivery
within that period. Individual records are managed-access; open publications
or abstraction forms do not grant unrestricted participant-data redistribution.
[Access process](https://www.bristol.ac.uk/alspac/researchers/access/).

**Decision:** useful HDP replication candidate after access and harmonization;
GDM candidate with historical ascertainment caveats; sPTB only after onset/PPROM
and indication audit. Older care practices and low recorded GDM frequency limit
modern transportability. Not an immediate hackathon download.

## 3. HAPO / HAPO-FUS

**Official source:** [NIDDK HAPO-FUS catalog](https://repository.niddk.nih.gov/study/150).
The catalog lists 4,697 participants for the release; do not equate that with the
23,316 participants in the original blinded HAPO analysis. Pregnancy records are
linked to later mother/child follow-up, not continuous prenatal sensor records.
The original multinational cohort studied singleton pregnancies without known
pre-existing diabetes; the follow-up release is a selected subset.
[Original population/protocol](https://diabetesjournals.org/care/article-pdf/35/3/574/610414/574.pdf).

The original study used an OGTT at 24–32 weeks, near 28 weeks. It documents
glucose assays, anthropometry, history and HDP classification from BP/chart
measurements. [Original HDP report](https://pmc.ncbi.nlm.nih.gov/articles/PMC2836485/),
[HAPO/FUS methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC8329103/).
The official integrity report lists the retrospective IADPSG GDM field
`preg_IADPSG_gdm_mom` and prenatal OGTT/mean arterial pressure variables.
[Release integrity report](https://repository.niddk.nih.gov/media/studies/hapo-fus/DSIC/HAPO-FUS_DSIC.pdf).
Exact longitudinal BP export and spontaneous-delivery subtype are NC.

**Access:** registration/application, eligible institutional PI, IRB determination,
DUA and approval. Current NIDDK notices add controlled-data security requirements;
this is not an anonymous student download or an open-license dataset.
[Request FAQ](https://repository.niddk.nih.gov/faq),
[current access notices](https://repository.niddk.nih.gov/home).

**Decision:** useful for GDM label/assay research and HDP after release audit.
Using OGTT glucose to predict a label defined by the same OGTT is diagnostic
reconstruction, not prediction of later GDM. Earlier predictors and timing must
be established. Generic prematurity cannot supply sPTB labels.

## 4. NICHD Fetal Growth Studies (FGS)

**Official source:** [NICHD FGS](https://www.nichd.nih.gov/about/org/diphr/officebranch/eb/fetal-growth-stud).
The US multicentre study includes 2,334 low-risk singleton participants, a separate
468-person obesity cohort, and 171 dichorionic twin pregnancies. It collected
repeat ultrasound, anthropometry, nutrition and blood specimens.

Early HbA1c and subsequent GDM are documented in an analysis of 107 cases and
214 controls; that nested case-control sample is not the full cohort or natural
GDM prevalence. [NIH early-biomarker report](https://www.nichd.nih.gov/newsroom/news/081618-gestational-diabetes).
Individual longitudinal study data exist, but exact shared assays, time fields,
HDP/sPTB labels and wearable variables were not verified in a release dictionary.

**Access:** the current [BRADS page](https://www.nichd.nih.gov/about/org/dir/dph/research/BRADS)
directs investigators to inquire about access. License, application/registration
steps, authorized release and processing time require confirmation; do not assume
open download from an older BRADS link.

**Decision:** a promising GDM alternative if early assays and later labels are
actually shared. Not immediately usable. Case-control sampling would require
sampling fractions/full-cohort validation before estimating absolute probability.

## 5. PhysioNet: visceral adipose tissue during pregnancy

**Official source:** [Version 1.0.0](https://physionet.org/content/maternal-visceral-adipose/1.0.0/),
[original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC7192370/).
Brazilian singleton cohort enrolled by 20 weeks; 154 recruited, 133 followed.
Public data contain one intake row plus delivery outcomes per pregnancy, not
longitudinal CGM/BP. GDM comes from routine records using mixed ascertainment.
HDP and spontaneous-delivery labels are not released.

**Access:** anonymous public CSV, Open Data Commons Attribution 1.0;
no registration/application. Attribute the resource and retain license terms.

**File audit:** downloaded the [official CSV](https://physionet.org/files/maternal-visceral-adipose/1.0.0/visceral_fat.csv)
to `/tmp` only. It has **133 rows, 18 GDM-positive / 115 negative**, and 30 missing
fasting-glucose values. One prior-DM field equals 1 despite the documented
pre-existing-diabetes exclusion. There are no diagnosis dates. CSV SHA256:
`2ffeff87063bb8bf4c46c7d1c16cf670d183e3873979cc38db3a9a8e958055c0`.
Gestational-age fields use weeks and days; do not parse their comma-separated
strings as decimal weeks.

**Decision:** accessible for a small offline feasibility audit, not a credible
CGM model or dated future-GDM forecast. Resolve eligibility and whether fasting
glucose already contributed to diagnosis before supervised modeling. Exclude
birth weight, delivery mode and birth gestation from predictors. Never count
delivery information as intake data.

## 6. MFMU Preterm Prediction Study (PREDS)

**Official source:** [MFMU dataset catalog](https://mfmunetwork.bsc.gwu.edu/web/mfmunetwork/datasets)
lists the singleton PREDS release in NICHD DASH. The original singleton study
recruited 3,073; principal analyses used 2,929 after exclusions/losses. The exact
current release count requires verification.
[Original population report](https://www.sciencedirect.com/science/article/abs/pii/S0002937899701110).

US participants included nulliparous and multiparous asymptomatic singletons,
assessed at approximately 23–24 weeks. Repeat cervical length at 24/28 weeks and
fetal fibronectin at 24/26/28/30 weeks are documented. Outcomes explicitly include
spontaneous preterm delivery, including PPROM-associated delivery.
[Sequential measurements](https://doi.org/10.1067/mob.2000.104212),
[PPROM outcome study](https://doi.org/10.1067/mob.2000.106766).

**Access:** DASH registration/request, DUA/approval and study-specific IRB
requirements as described in [DASH policy](https://dash.nichd.nih.gov/resource/policies).
No open redistribution license verified. Migration and current release availability
must be checked; not a guaranteed hackathon download.

**Decision:** strong sPTB candidate when cervical length and prior obstetric
history are needed. HDP/GDM target labels are NC. Confirm the release includes
dated visits and delivery etiology; do not use twins from a different study
population interchangeably or import later fibronectin measurements at an early origin.

## 7. PhysioNet TPEHG DB

**Official source:** [TPEHG DB 1.0.1](https://physionet.org/content/tpehgdb/1.0.1/).
Slovenian records collected 1997–2005: 300 pregnancies, one 30-minute EHG recording
each, about 22 or 32 weeks; 38 repository preterm / 262 term records. No serial
pregnancy history beyond the accompanying fields is provided.

Induced labour and Caesarean deliveries were excluded. This selected sample is
not an adjudicated population-wide sPTB cohort. Documentation inconsistently
describes the boundary as ≤37 versus <37 weeks: audit gestation precision and
labels before using the requested strict <37 target. Hypertension/diabetes
indicators are not future HDP/GDM outcomes; funneling is not cervical length.

**Access:** public files; Open Data Commons Attribution 1.0; no account/application.
**Decision:** immediate signal-method feasibility only. Requires EHG features
unavailable in Nestwatch, few positive pregnancies, and target verification.
Keep recordings/channels/segments together in splits. Never use final gestation,
`Premature`, `Group`, outcome-bearing filenames or label columns as features.

## 8. PhysioNet TPEHGT with tocogram

**Official source:** [TPEHGT 1.0.0](https://physionet.org/content/tpehgt/1.0.0/).
Slovenian spontaneous-delivery dataset: 13 preterm recordings from **8 pregnancies**
and 13 term recordings from **10 pregnancies**, plus five nonpregnant recordings.
It has 30-minute EHG/TOCO traces and annotated contraction intervals, usually
around 31 weeks. Some pregnancies have repeat recordings.

**Access:** public files; Open Data Commons Attribution 1.0; no account/application.
**Decision:** narrow sPTB signal research only. Eighteen pregnancies cannot support
a credible standalone clinical model. Establish pregnancy-level linkage before
splitting; recording IDs alone are not proven patient IDs. Exclude nonpregnant
records and keep pregnancy segments together. Its selected, balanced recording
counts do not establish general-population prevalence. No HDP/GDM outcome support.

## Datasets not suitable for these targets

- [UCI Maternal Health Risk](https://archive.ics.uci.edu/dataset/863/maternal%2Bhealth%2Brisk)
  has generic `RiskLevel` categories, not timed HDP/GDM/sPTB diagnoses. BP,
  glucose and HR columns cannot supply missing outcome labels.
- General-population diabetes/CGM data, synthetic pregnancy datasets, outcome-only
  neonatal data and aggregate tables cannot establish prenatal condition targets
  merely because some features overlap. A publication mentioning wearables does
  not prove an accessible, labeled, individual-level pregnancy release exists.

## Remaining verification before any training

For the chosen release, record exact version/license, independent pregnancies,
positive/negative events, exclusions, missingness, predictor collection times,
diagnosis/onset/availability times, complete follow-up and label definitions.
Verify prenatal rather than postpartum variables and source units. Confirm
spontaneous labour/PPROM versus indicated delivery using etiology, not delivery
mode. Assess required predictor parameters against event counts, then request
user review of the final dataset/target before implementing a disease model.
