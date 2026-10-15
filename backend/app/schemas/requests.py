"""Request bodies. Server-owned fields (authors, timestamps, roles of the caller) are never accepted."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import (
    BedId,
    Email,
    LongText,
    OptionalShortText,
    Password,
    PersonName,
    Phone,
    Reason,
    ShortText,
    StrictModel,
)

Role = Literal["nurse", "physician", "biomed", "admin"]
Scenario = Literal["normal", "low_spo2", "weak_battery", "sensor_issue", "lost_connection"]
Parameter = Literal["heart_rate", "spo2", "resp_rate", "systolic", "diastolic"]

PARAMETER_RANGES: dict[str, tuple[int, int]] = {
    "heart_rate": (20, 250),
    "spo2": (50, 100),
    "resp_rate": (4, 60),
    "systolic": (50, 250),
    "diastolic": (30, 150),
}


# ---------------------------------------------------------------- auth / me
class LoginIn(StrictModel):
    email: Email
    password: Password


class RecoverIn(StrictModel):
    email: Email


class ResetPasswordIn(StrictModel):
    access_token: str = Field(min_length=20, max_length=8192)
    new_password: Password


class ChangePasswordIn(StrictModel):
    current_password: Password
    new_password: Password


class ProfileUpdateIn(StrictModel):
    full_name: PersonName
    job_title: OptionalShortText = ""
    phone: Phone = ""


class PreferencesIn(StrictModel):
    landing_page: Literal["/", "/patients", "/monitoring", "/alarms", "/devices", "/reports"] = "/"
    alarm_sound: bool = True
    density: Literal["comfortable", "compact"] = "comfortable"
    ward_view: Literal["grid", "3d"] = "grid"
    critical_banner: bool = True


class ConsentIn(StrictModel):
    version: Literal["2026-10"]


class PrivacyRequestIn(StrictModel):
    kind: Literal["deletion"]
    details: OptionalShortText = ""


# ---------------------------------------------------------------- patients
class PatientSearchIn(StrictModel):
    q: OptionalShortText = ""
    status: Literal["admitted", "discharged", "all"] = "admitted"
    acuity: Literal["low", "medium", "high", "all"] = "all"
    alarm: Literal["any", "active", "none"] = "any"
    monitored: Literal["any", "yes", "no"] = "any"
    sort: Literal["bed", "name", "acuity", "admitted"] = "bed"
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=25, ge=1, le=100)


class PatientUpdateIn(StrictModel):
    diagnosis: ShortText
    attending_physician: PersonName
    acuity: Literal["low", "medium", "high"]
    allergies: ShortText
    code_status: Literal["Full code", "DNR", "DNI", "DNR/DNI", "Comfort care"]


class RestrictionIn(StrictModel):
    restricted: bool


class NoteIn(StrictModel):
    category: Literal["nursing", "physician", "handover", "device"]
    body: LongText


class EmergencyAccessIn(StrictModel):
    reason: Reason


# ---------------------------------------------------------------- thresholds
class ThresholdIn(StrictModel):
    parameter: Parameter
    low: float | None = None
    high: float | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> "ThresholdIn":
        lo, hi = PARAMETER_RANGES[self.parameter]
        for value in (self.low, self.high):
            if value is not None and not (lo <= value <= hi):
                raise ValueError(f"{self.parameter} limits must be between {lo} and {hi}")
        if self.low is not None and self.high is not None and self.low >= self.high:
            raise ValueError("the low limit must be below the high limit")
        if self.low is None and self.high is None and self.enabled:
            raise ValueError("set at least one limit or disable the alarm")
        return self


class ThresholdSetIn(StrictModel):
    items: list[ThresholdIn] = Field(default_factory=list, max_length=5)
    reset_to_default: list[Parameter] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _check(self) -> "ThresholdSetIn":
        if not self.items and not self.reset_to_default:
            raise ValueError("nothing to change")
        params = [i.parameter for i in self.items]
        if len(params) != len(set(params)):
            raise ValueError("each parameter may appear only once")
        return self


# ---------------------------------------------------------------- alarms
class AckIn(StrictModel):
    note: OptionalShortText = ""


# ---------------------------------------------------------------- devices
class AssignIn(StrictModel):
    bed_id: BedId


class MonitorUpdateIn(StrictModel):
    status: Literal["active", "standby", "maintenance", "retired"] | None = None
    next_maintenance_due: date | None = None


class MaintenanceIn(StrictModel):
    type: Literal["inspection", "battery_replacement", "sensor_replacement", "repair", "calibration", "issue_report"]
    description: LongText = Field(max_length=1000)


class MaintenanceUpdateIn(StrictModel):
    status: Literal["open", "in_progress", "completed"]
    resolution: OptionalShortText = ""


# ---------------------------------------------------------------- reports
class ReportIn(StrictModel):
    kind: Literal["shift_summary", "alarm_log", "device_maintenance", "patient_vitals"]
    period_hours: int = Field(default=12, ge=1, le=168)
    patient_id: UUID | None = None
    deidentified: bool = False

    @model_validator(mode="after")
    def _check(self) -> "ReportIn":
        if self.kind == "patient_vitals" and self.patient_id is None:
            raise ValueError("choose a patient for a vitals report")
        return self


# ---------------------------------------------------------------- simulation
class ScenarioIn(StrictModel):
    scenario: Scenario


class AdvanceIn(StrictModel):
    steps: int = Field(default=1, ge=1, le=120)
    source: Literal["manual", "auto"] = "manual"


class ResetIn(StrictModel):
    confirm: Literal["RESET"]


# ---------------------------------------------------------------- team
class InviteIn(StrictModel):
    email: Email
    full_name: PersonName
    role: Role
    job_title: OptionalShortText = ""


class TeamUpdateIn(StrictModel):
    role: Role | None = None
    active: bool | None = None


class PrivacyDecisionIn(StrictModel):
    status: Literal["completed", "rejected"]


# ---------------------------------------------------------------- device ingestion
class DeviceReadingIn(StrictModel):
    heart_rate: int | None = Field(default=None, ge=20, le=300)
    spo2: int | None = Field(default=None, ge=40, le=100)
    resp_rate: int | None = Field(default=None, ge=0, le=80)
    systolic: int | None = Field(default=None, ge=40, le=300)
    diastolic: int | None = Field(default=None, ge=20, le=200)
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    quality: Literal["good", "artifact", "no_signal"] = "good"
