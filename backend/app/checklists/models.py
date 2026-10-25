from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import SmallInteger
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Entity, Versioned


class Template(Versioned):
    __tablename__ = "checklist_templates"
    name: Mapped[str]
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))  # 0 = Monday
    due_minutes: Mapped[int]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    active: Mapped[bool]


class Run(Entity):
    __tablename__ = "checklist_runs"
    template_id: Mapped[UUID]
    name: Mapped[str]
    business_date: Mapped[date]
    due_at: Mapped[datetime]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None]
    alerted_at: Mapped[datetime | None]


class Check(Entity):
    __tablename__ = "checklist_checks"
    run_id: Mapped[UUID]
    item_id: Mapped[UUID]
    checked: Mapped[bool]
    checked_at: Mapped[datetime]
