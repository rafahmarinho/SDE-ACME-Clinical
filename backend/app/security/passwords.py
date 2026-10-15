"""Password policy (configurable minimum length; enforced server-side on every password change).

Supabase Auth must be configured with the same or stricter rules (see README); this check runs
before any password reaches Supabase so the policy cannot be bypassed from the browser.
"""

import string

from app.config import get_settings

COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345",
    "iloveyou1234", "admin1234567", "changeme1234", "p@ssw0rd1234", "passw0rd!234", "acmeclinical1",
    "acme-clinical", "hospital1234", "nurse1234567", "doctor123456",
}


def policy() -> dict:
    settings = get_settings()
    return {
        "min_length": settings.password_min_length,
        "max_length": 128,
        "requires": ["lowercase", "uppercase", "digit", "symbol"],
    }


def problems(password: str, email: str | None = None) -> list[str]:
    settings = get_settings()
    issues: list[str] = []
    if len(password) < settings.password_min_length:
        issues.append(f"Use at least {settings.password_min_length} characters.")
    if len(password) > 128:
        issues.append("Use at most 128 characters.")
    if not any(c.islower() for c in password):
        issues.append("Add a lowercase letter.")
    if not any(c.isupper() for c in password):
        issues.append("Add an uppercase letter.")
    if not any(c.isdigit() for c in password):
        issues.append("Add a number.")
    if not any(c in string.punctuation or (not c.isalnum() and not c.isspace()) for c in password):
        issues.append("Add a symbol.")
    if password.lower() in COMMON_PASSWORDS:
        issues.append("This password is too common.")
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in password.lower():
            issues.append("Do not include your e-mail name in the password.")
    if any(ord(c) < 32 for c in password):
        issues.append("Remove control characters.")
    return issues
