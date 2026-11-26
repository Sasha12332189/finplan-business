"""Data model of finplan Business (spec section 3).

Money is always Numeric/Decimal. Dates of operations are the business's local date;
timestamps (created_at, plan_until…) are naive UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

MONEY = Numeric(16, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """A Telegram person. One person can own a business and be a member of others."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="uk")
    theme: Mapped[str] = mapped_column(String(16), default="system")
    active_business_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A referral code seen in /start before the person created a business.
    pending_referral: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="fop")  # fop | company | freelance
    fop_group: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 | 2 | 3 | None
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5"))  # percent, group 3
    is_vat_payer: Mapped[bool] = mapped_column(Boolean, default=False)
    pays_esv: Mapped[bool] = mapped_column(Boolean, default=True)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    timezone: Mapped[str] = mapped_column(String(48), default="Europe/Kyiv")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    plan: Mapped[str] = mapped_column(String(16), default="free")  # free | pro | team (paid plan)
    plan_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan_period: Mapped[str | None] = mapped_column(String(8), nullable=True)  # month | year
    plan_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # the Stars subscription
    plan_canceled: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    referred_by_business_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Automatic messages
    daily_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_report: Mapped[bool] = mapped_column(Boolean, default=True)
    # JSON list of keys of reminders already sent ("tax:2026-Q4:7", "limit:2026:90", "daily:2026-11-26"…)
    notices: Mapped[str] = mapped_column(Text, default="[]")
    invoice_counter: Mapped[int] = mapped_column(Integer, default=0)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("business_id", "telegram_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="owner")  # owner | admin | staff | accountant
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invite(Base):
    """One-time invitation link: t.me/<bot>?start=inv_<token>."""
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="staff")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16), default="client")  # client | supplier | both
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))  # income | expense
    is_cogs: Mapped[bool] = mapped_column(Boolean, default=False)
    # Key of a default category ("sales", "rent"…) so quick entry keywords work in any language.
    key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    bank: Mapped[str | None] = mapped_column(String(16), nullable=True)  # mono | privat | None
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(8))  # income | expense | transfer
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    amount_base: Mapped[Decimal] = mapped_column(MONEY)  # in the business currency
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    counterparty_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # transfers
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(12), default="app")  # bot | app | ai | bank | recurring
    bank_tx_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    attachment_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Stock: a sale of a product lowers its stock and records the cost of goods sold.
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    cogs_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    counterparty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items: Mapped[str] = mapped_column(Text, default="[]")  # JSON [{"name", "qty", "price"}]
    total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | sent | paid | overdue | cancelled
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_operation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    counterparty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(10))  # they_owe | we_owe
    amount: Mapped[Decimal] = mapped_column(MONEY)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecurringOperation(Base):
    __tablename__ = "recurring_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="expense")
    amount: Mapped[Decimal] = mapped_column(MONEY)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counterparty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    day_of_month: Mapped[int] = mapped_column(Integer, default=1)
    next_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaxPeriod(Base):
    __tablename__ = "tax_periods"
    __table_args__ = (UniqueConstraint("business_id", "period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(8))  # 2026-Q4
    income_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    single_tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    esv: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    military_levy: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(8), default="due")  # due | paid
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(16), default="шт")
    cost_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    sale_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    bank: Mapped[str] = mapped_column(String(16))  # mono | privat
    token_encrypted: Mapped[str] = mapped_column(Text)
    client_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # PrivatBank Autoclient "id"
    account_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    account_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # our Account the money lands on
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    plan: Mapped[str] = mapped_column(String(16))
    stars: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(8))  # month | year
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AiUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("business_id", "member_id", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(String(7))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class AiDraft(Base):
    """Something the AI assistant proposes to write. Nothing is written until a person confirms it."""
    __tablename__ = "ai_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(24))  # add_operation | add_debt | create_invoice
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | done | rejected
    result_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # excel | pdf | csv
    period: Mapped[str] = mapped_column(String(32))
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
