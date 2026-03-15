"""
Pydantic models for personal-finance transactions.

Hierarchy
---------
Category          – enum of recognised spending/income categories
AccountType       – enum of supported account kinds
Transaction       – single financial event (one row in a statement)
TransactionSet    – ordered collection of Transactions with statement metadata
"""

from __future__ import annotations

import enum
from datetime import date
from typing import Optional

import pandas as pd
from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Category(str, enum.Enum):
    """Standardised spending / income categories for a transaction."""

    HOUSING        = "HOUSING"        # rent, mortgage, property tax, insurance
    GROCERIES      = "GROCERIES"      # supermarkets, bulk stores
    DINING         = "DINING"         # restaurants, cafés, food delivery
    TRANSPORTATION = "TRANSPORTATION" # gas, transit, rideshare, parking
    UTILITIES      = "UTILITIES"      # hydro, gas, internet, phone
    SUBSCRIPTIONS  = "SUBSCRIPTIONS"  # streaming, SaaS, gym memberships
    SHOPPING       = "SHOPPING"       # retail, e-commerce, clothing
    TRAVEL         = "TRAVEL"         # flights, hotels, car rentals
    INCOME         = "INCOME"         # salary, freelance, deposits
    TRANSFER       = "TRANSFER"       # inter-account moves, e-transfers
    OTHER          = "OTHER"          # anything clearly identified but uncategorised
    UNCATEGORIZED  = "UNCATEGORIZED"  # default when no category is assigned


class AccountType(str, enum.Enum):
    """The kind of financial account a transaction belongs to."""

    CHEQUING = "chequing"
    CREDIT   = "credit"
    MORTGAGE = "mortgage"


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

# Inclusive date bounds used for validation
_DATE_MIN = date(2020, 1, 1)
_DATE_MAX = date(2030, 12, 31)


class Transaction(BaseModel):
    """A single financial event parsed from a bank or credit-card statement.

    Sign convention
    ---------------
    ``amount > 0``  → money **received** (income, refund, credit)
    ``amount < 0``  → money **spent**    (expense, debit, charge)

    Attributes
    ----------
    date:
        The transaction date as it appears on the statement.
    description:
        Cleaned, human-readable merchant / payee name.
    amount:
        Transaction value in CAD; non-zero, positive = income.
    category:
        Optional spend category; defaults to ``UNCATEGORIZED``.
    account_type:
        The account kind this transaction came from.
    source_file:
        Filename (or path) of the statement the row was parsed from.
    raw_description:
        Original description string before any normalisation.
    """

    date:            date
    description:     str
    amount:          float
    category:        Category = Category.UNCATEGORIZED
    account_type:    AccountType
    source_file:     str
    raw_description: str

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("amount")
    @classmethod
    def amount_must_be_nonzero(cls, v: float) -> float:
        """Reject zero-value transactions — they carry no financial meaning."""
        if v == 0.0:
            raise ValueError("amount cannot be 0")
        return round(v, 2)

    @field_validator("date")
    @classmethod
    def date_must_be_in_range(cls, v: date) -> date:
        """Reject dates outside 2020-01-01 … 2030-12-31."""
        if not (_DATE_MIN <= v <= _DATE_MAX):
            raise ValueError(
                f"date {v} is outside the allowed range "
                f"({_DATE_MIN} – {_DATE_MAX})"
            )
        return v

    @field_validator("description", "raw_description")
    @classmethod
    def string_must_not_be_blank(cls, v: str) -> str:
        """Strip surrounding whitespace and reject empty strings."""
        v = v.strip()
        if not v:
            raise ValueError("field must not be blank")
        return v

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_expense(self) -> bool:
        """Return True when this transaction reduces the account balance."""
        return self.amount < 0

    @property
    def is_income(self) -> bool:
        """Return True when this transaction increases the account balance."""
        return self.amount > 0

    @property
    def absolute_amount(self) -> float:
        """Absolute value of the transaction amount."""
        return abs(self.amount)


# ---------------------------------------------------------------------------
# TransactionSet
# ---------------------------------------------------------------------------

class TransactionSet(BaseModel):
    """An ordered collection of Transactions from a single statement.

    Attributes
    ----------
    transactions:
        The list of parsed Transaction objects, ordered by date ascending.
    source:
        File path or URI the data was loaded from.
    account_name:
        Human-readable account label (e.g. ``"RBC Chequing"``).
    institution:
        Financial institution name (e.g. ``"Royal Bank of Canada"``).
    period_start:
        First date covered by this statement (inclusive).
    period_end:
        Last date covered by this statement (inclusive).
    """

    transactions: list[Transaction]
    source:       str
    account_name: str
    institution:  str
    period_start: Optional[date] = None
    period_end:   Optional[date] = None

    # ------------------------------------------------------------------
    # Cross-field validation
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def derive_period_from_transactions(self) -> "TransactionSet":
        """Auto-populate period_start / period_end from transaction dates
        when they are not explicitly provided."""
        if self.transactions and self.period_start is None:
            self.period_start = min(t.date for t in self.transactions)
        if self.transactions and self.period_end is None:
            self.period_end   = max(t.date for t in self.transactions)
        return self

    @model_validator(mode="after")
    def period_start_before_end(self) -> "TransactionSet":
        """Ensure period_start does not fall after period_end."""
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start > self.period_end
        ):
            raise ValueError(
                f"period_start ({self.period_start}) must be ≤ "
                f"period_end ({self.period_end})"
            )
        return self

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def total_income(self) -> float:
        """Sum of all positive (income) amounts."""
        return round(sum(t.amount for t in self.transactions if t.is_income), 2)

    @property
    def total_expenses(self) -> float:
        """Sum of all negative (expense) amounts (returned as a negative number)."""
        return round(sum(t.amount for t in self.transactions if t.is_expense), 2)

    @property
    def net(self) -> float:
        """Net cash flow: income + expenses (expenses are already negative)."""
        return round(sum(t.amount for t in self.transactions), 2)

    @property
    def count(self) -> int:
        """Number of transactions in this set."""
        return len(self.transactions)

    # ------------------------------------------------------------------
    # DataFrame export
    # ------------------------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        """Export all transactions to a :class:`pandas.DataFrame`.

        Each row corresponds to one :class:`Transaction`.  Enum fields are
        exported as their string values so downstream code does not need to
        import the enum types.

        Returns
        -------
        pandas.DataFrame
            Columns: ``date``, ``description``, ``amount``, ``category``,
            ``account_type``, ``source_file``, ``raw_description``,
            plus statement-level metadata columns ``account_name``,
            ``institution``, ``period_start``, ``period_end``.

        Examples
        --------
        >>> df = transaction_set.to_dataframe()
        >>> df.groupby("category")["amount"].sum()
        """
        if not self.transactions:
            return pd.DataFrame(columns=[
                "date", "description", "amount", "category",
                "account_type", "source_file", "raw_description",
                "account_name", "institution", "period_start", "period_end",
            ])

        rows = [
            {
                "date":            t.date,
                "description":     t.description,
                "amount":          t.amount,
                "category":        t.category.value,
                "account_type":    t.account_type.value,
                "source_file":     t.source_file,
                "raw_description": t.raw_description,
                # Denormalised statement metadata — handy when merging sets
                "account_name":    self.account_name,
                "institution":     self.institution,
                "period_start":    self.period_start,
                "period_end":      self.period_end,
            }
            for t in self.transactions
        ]
        df = pd.DataFrame(rows)
        df["date"]         = pd.to_datetime(df["date"])
        df["period_start"] = pd.to_datetime(df["period_start"])
        df["period_end"]   = pd.to_datetime(df["period_end"])
        df["category"]     = df["category"].astype("category")
        df["account_type"] = df["account_type"].astype("category")
        return df.sort_values("date").reset_index(drop=True)
