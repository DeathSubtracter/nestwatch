"""The locally owned synthetic patient context."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class GestationalAge(BaseModel):
    weeks: int = Field(ge=0)
    days: int = Field(ge=0, le=6)
    as_of_date: date


class DiabetesContext(BaseModel):
    type: Literal["type_2"]
    since_date: date
    context: str


class Symptom(BaseModel):
    timestamp: datetime
    name: str
    severity: str
    notes: str


class Patient(BaseModel):
    patient_id: Literal["maya"]
    display_name: str
    synthetic: Literal[True]
    gestational_age: GestationalAge
    glp1_last_dose_date: date
    medication_transition_date: date
    diabetes: DiabetesContext
    current_treatment_text: str
    symptoms: list[Symptom]
