"""Response model for GET /api/v1/dashboard/summary (P-9).

Every figure is computed from stored rows for the signed-in user only; nothing
is estimated or filled in. Money is integer paise.

Risk statistics are deliberately absent: the stored assessments so far are
development-seed samples, not risk-engine output. They are added once the
scoring pipeline exists.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DashboardPeriod(BaseModel):
    days: int = Field(description="Length of the rolling window in days (always 30).")
    start: datetime = Field(description="Window start (inclusive), UTC: end minus 30 days.")
    end: datetime = Field(description="Window end (inclusive), UTC: the time of the request.")


class TransactionStatusCounts(BaseModel):
    """Stored status of the user's transactions created in the window. Every key is always present."""

    model_config = ConfigDict(extra="forbid")

    INITIATED: int = 0
    ANALYSED: int = 0
    AWAITING_USER_ACTION: int = 0
    APPROVED: int = 0
    CANCELLED: int = 0
    EXPIRED: int = 0
    FAILED: int = 0


class DashboardTransactions(BaseModel):
    total: int = Field(description="Transactions created in the window, any status.")
    by_status: TransactionStatusCounts
    awaiting_action: int = Field(
        description=(
            "AWAITING_USER_ACTION transactions in the window whose decision deadline (expires_at) has "
            "not passed. One past its deadline but not yet marked EXPIRED is counted in "
            "by_status.AWAITING_USER_ACTION (its stored state) but not here."
        )
    )
    approved_amount_paise: int = Field(description="Sum of amount_paise of APPROVED transactions in the window.")


class DashboardAlerts(BaseModel):
    unread: int = Field(description="All of the user's alerts not yet marked read, at any date (not limited to the window).")


class DashboardSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "period": {"days": 30, "start": "2026-10-10T18:00:00Z", "end": "2026-11-09T18:00:00Z"},
                "transactions": {
                    "total": 10,
                    "by_status": {
                        "INITIATED": 0,
                        "ANALYSED": 0,
                        "AWAITING_USER_ACTION": 1,
                        "APPROVED": 7,
                        "CANCELLED": 1,
                        "EXPIRED": 1,
                        "FAILED": 0,
                    },
                    "awaiting_action": 1,
                    "approved_amount_paise": 4459000,
                },
                "alerts": {"unread": 3},
            }
        }
    )

    period: DashboardPeriod
    transactions: DashboardTransactions
    alerts: DashboardAlerts
