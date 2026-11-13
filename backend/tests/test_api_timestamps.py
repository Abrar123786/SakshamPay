"""API timestamps (no database): one UTC form for every response timestamp.

See ``app/schemas/common.py`` and tests/test_api_timestamps_postgres.py for the
PostgreSQL regression this guards.
"""

import inspect
import typing
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import AfterValidator, BaseModel, ValidationError

from app import schemas
from app.schemas import auth, beneficiaries, common, dashboard, system, transactions
from app.schemas.common import UtcDateTime, as_utc

INSTANT = datetime(2026, 11, 13, 11, 59, 57, 827761, tzinfo=UTC)


class Probe(BaseModel):
    at: UtcDateTime
    maybe: UtcDateTime | None = None


@pytest.mark.parametrize(
    "value",
    [
        INSTANT,
        INSTANT.astimezone(ZoneInfo("Asia/Kolkata")),  # how psycopg returns it from an IST session
        INSTANT.astimezone(ZoneInfo("Asia/Calcutta")),
        INSTANT.astimezone(ZoneInfo("UTC")),
        INSTANT.astimezone(timezone(timedelta(hours=-7))),
    ],
)
def test_every_zone_serialises_to_the_same_utc_string(value):
    probe = Probe(at=value, maybe=value)
    assert probe.model_dump_json() == '{"at":"2026-11-13T11:59:57.827761Z","maybe":"2026-11-13T11:59:57.827761Z"}'
    assert probe.at == value and probe.at.utcoffset() == timedelta(0)  # same instant, now in UTC


def test_the_two_strings_from_the_bug_report_are_one_instant():
    original = Probe(at=datetime.fromisoformat("2026-11-13T11:59:57.827761Z"))
    replayed = Probe(at=datetime.fromisoformat("2026-11-13T17:29:57.827761+05:30"))
    assert original.model_dump_json() == replayed.model_dump_json()


def test_microseconds_are_kept_and_none_stays_none():
    assert Probe(at=INSTANT.replace(microsecond=1)).model_dump()["at"].microsecond == 1
    assert Probe(at=INSTANT).maybe is None


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValidationError, match="timezone-aware"):
        Probe(at=datetime(2026, 11, 13, 12, 0))


def _datetime_annotations(annotation):
    """Yield (is_wrapped_in_as_utc) for every datetime inside a field annotation."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        base, *metadata = typing.get_args(annotation)
        if base is datetime:
            yield any(isinstance(m, AfterValidator) and m.func is as_utc for m in metadata)
            return
        yield from _datetime_annotations(base)
    elif annotation is datetime:
        yield False
    else:
        for arg in typing.get_args(annotation):
            yield from _datetime_annotations(arg)


def test_every_response_timestamp_uses_the_utc_type():
    """A new response field typed plain ``datetime`` would bring the bug back."""
    checked = []
    for module in (auth, beneficiaries, common, dashboard, system, transactions):
        for _, model in inspect.getmembers(module, inspect.isclass):
            if not issubclass(model, BaseModel) or model.__module__ != module.__name__:
                continue
            for name, field in model.model_fields.items():
                annotation = typing.Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
                for wrapped in _datetime_annotations(annotation):
                    checked.append(f"{model.__name__}.{name}")
                    assert wrapped, f"{model.__name__}.{name} must be UtcDateTime"
    assert {"TransactionOut.expires_at", "AssessmentOut.assessed_at", "BeneficiaryOut.created_at",
            "UserProfile.created_at", "TokenResponse.expires_at", "DashboardPeriod.start"} <= set(checked)
    assert schemas  # the package itself imports cleanly
