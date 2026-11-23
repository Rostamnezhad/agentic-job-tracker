"""Validated job entries, independent of the CLI and storage."""

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit


STATUSES = ("saved", "applied", "interview", "offer", "rejected", "withdrawn")


@dataclass(frozen=True)
class JobEntry:
    company: str
    role: str
    url: str
    status: str = "saved"
    applied_date: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        for field in ("company", "role", "url"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"{field} must not contain control characters")
            object.__setattr__(self, field, value.strip())

        try:
            parts = urlsplit(self.url)
            valid_url = (
                parts.scheme in ("http", "https")
                and bool(parts.hostname)
                and parts.username is None
                and parts.password is None
                and not any(char.isspace() for char in self.url)
                and "\\" not in self.url
            )
            # Accessing port also rejects invalid ports, such as :abc or :99999.
            parts.port
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("url must be an absolute HTTP(S) URL without credentials")

        if self.status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(STATUSES)}")

        if self.applied_date is not None:
            try:
                parsed = date.fromisoformat(self.applied_date)
            except (ValueError, TypeError) as exc:
                raise ValueError("applied_date must be a real date in YYYY-MM-DD format") from exc
            if parsed.isoformat() != self.applied_date:
                raise ValueError("applied_date must use YYYY-MM-DD format")

        if self.status == "saved" and self.applied_date is not None:
            raise ValueError("a saved job has no applied_date; use --status applied")
        if self.status != "saved" and self.applied_date is None:
            raise ValueError(f"applied_date is required for status '{self.status}'")
