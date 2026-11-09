"""Data-minimisation helpers (P-1 security design, P-4 schema).

* Account references and UPI IDs are never stored in full: only a display mask and
  a keyed fingerprint (HMAC-SHA256 with ``IDENTIFIER_HASH_KEY``). The fingerprint
  detects duplicates and repeat payees without being reversible.
* Device IDs are stored only as a keyed hash.
* IP addresses are truncated to a /24 (IPv4) or /48 (IPv6) network.

Fingerprints are domain-separated ("account:", "upi:", "device:") so equal strings
of different kinds never collide.
"""

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass

from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import AppError

ACCOUNT_REFERENCE_PATTERN = re.compile(r"^[A-Z0-9]{6,34}$")
UPI_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,255}@[a-z][a-z0-9]{1,63}$")


class IdentifierKeyMissingError(AppError):
    status_code = 500
    code = "CONFIGURATION_ERROR"
    message = "IDENTIFIER_HASH_KEY is not configured."


class InvalidIdentifierError(AppError):
    status_code = 422
    code = "INVALID_IDENTIFIER"
    message = "The payment identifier is not valid."


@dataclass(frozen=True)
class ProtectedIdentifier:
    """What is stored instead of a raw identifier."""

    masked: str
    fingerprint: str  # 64 lower-case hex characters


def identifier_key(settings: Settings) -> bytes:
    if settings.IDENTIFIER_HASH_KEY is None:
        raise IdentifierKeyMissingError()
    return settings.IDENTIFIER_HASH_KEY.get_secret_value().encode()


def _fingerprint(key: bytes | SecretStr, kind: str, value: str) -> str:
    raw_key = key.get_secret_value().encode() if isinstance(key, SecretStr) else key
    return hmac.new(raw_key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def normalise_account_reference(raw: str) -> str:
    value = re.sub(r"[\s-]", "", raw).upper()
    if not ACCOUNT_REFERENCE_PATTERN.fullmatch(value):
        raise InvalidIdentifierError("Account reference must be 6-34 letters or digits.")
    return value


def normalise_upi_id(raw: str) -> str:
    value = raw.strip().lower()
    if not UPI_ID_PATTERN.fullmatch(value):
        raise InvalidIdentifierError("UPI ID must look like name@handle.")
    return value


def protect_account_reference(raw: str, key: bytes | SecretStr) -> ProtectedIdentifier:
    value = normalise_account_reference(raw)
    return ProtectedIdentifier(masked="X" * (len(value) - 4) + value[-4:], fingerprint=_fingerprint(key, "account", value))


def protect_upi_id(raw: str, key: bytes | SecretStr) -> ProtectedIdentifier:
    value = normalise_upi_id(raw)
    name, handle = value.split("@", 1)
    return ProtectedIdentifier(masked=f"{name[:2]}****@{handle}", fingerprint=_fingerprint(key, "upi", value))


def hash_device_id(device_id: str, key: bytes | SecretStr) -> str:
    return _fingerprint(key, "device", device_id.strip())


def truncate_ip_address(raw: str | None) -> str | None:
    """'203.0.113.57' -> '203.0.113.0/24'; IPv6 -> /48. Invalid input -> None."""
    if not raw:
        return None
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
