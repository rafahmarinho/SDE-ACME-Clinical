"""Central authorization policy (role-based access control).

Every route declares the permission it needs through `require(...)`; this module is the single
place where roles are mapped to permissions. The frontend receives the same list from /me to
shape navigation, but the API never relies on the client for enforcement.
"""

from typing import Final

ROLES: Final = ("nurse", "physician", "biomed", "admin")
CLINICAL_ROLES: Final = frozenset({"nurse", "physician", "admin"})

PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "ward:view": frozenset(ROLES),
    "patients:view": CLINICAL_ROLES,
    "patients:edit": frozenset({"physician", "admin"}),
    "patients:restrict": frozenset({"admin"}),
    "vitals:view": CLINICAL_ROLES,
    "notes:view": CLINICAL_ROLES,
    "notes:create": frozenset({"nurse", "physician"}),
    "alarms:view": frozenset(ROLES),
    "alarms:ack_clinical": frozenset({"nurse", "physician"}),
    "alarms:ack_technical": frozenset({"nurse", "physician", "biomed"}),
    "thresholds:view": CLINICAL_ROLES,
    "thresholds:edit_patient": frozenset({"physician"}),
    "thresholds:edit_default": frozenset({"physician", "admin"}),
    "devices:view": frozenset(ROLES),
    "devices:assign": frozenset({"nurse", "biomed", "admin"}),
    "devices:manage": frozenset({"biomed", "admin"}),
    "maintenance:report": frozenset(ROLES),
    "maintenance:manage": frozenset({"biomed", "admin"}),
    "reports:clinical": CLINICAL_ROLES,
    "reports:devices": frozenset(ROLES),
    "simulation:view": frozenset({"biomed", "admin"}),
    # Demo clock: any signed-in role may advance the simulated monitors (Live monitoring auto-run).
    "simulation:advance": frozenset(ROLES),
    "simulation:control": frozenset({"biomed", "admin"}),
    "simulation:reset": frozenset({"admin"}),
    "team:manage": frozenset({"admin"}),
    "audit:view": frozenset({"admin"}),
    "emergency:request": frozenset({"biomed"}),
    "privacy:manage": frozenset({"admin"}),
}

# Permissions that are considered administrative access and need a second factor (AAL2)
# when REQUIRE_ADMIN_MFA is enabled.
MFA_PROTECTED: Final = frozenset({"team:manage", "audit:view", "simulation:reset", "privacy:manage", "patients:restrict"})

REPORT_KIND_PERMISSION: Final = {
    "shift_summary": "reports:clinical",
    "alarm_log": "reports:clinical",
    "patient_vitals": "reports:clinical",
    "device_maintenance": "reports:devices",
}


def allowed(role: str | None, permission: str) -> bool:
    if role is None:
        return False
    roles = PERMISSIONS.get(permission)
    if roles is None:  # unknown permission: deny by default
        return False
    return role in roles


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def ack_permission(category: str) -> str:
    return "alarms:ack_technical" if category == "technical" else "alarms:ack_clinical"
