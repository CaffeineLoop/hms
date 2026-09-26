"""Timeline query: one UNION ALL over every registered clinical-record table.

There is no timeline table. Each source contributes (event_type, rank, record id,
occurred_at, created_at) rows for one patient; PostgreSQL merges, orders and pages them.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, Integer, String, func, literal, select, union_all
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TimelineQuerySource:
    event_type: str
    rank: int  # tie-break between event types that share the same occurred_at
    model: type
    occurred_at: ColumnElement[datetime]
    # Optional visibility rule, e.g. "only results of RELEASED lab orders".
    where: ColumnElement[bool] | None = None


@dataclass(frozen=True)
class TimelineRow:
    event_type: str
    record_id: uuid.UUID
    occurred_at: datetime


class TimelineRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def page(
        self,
        patient_id: uuid.UUID,
        sources: list[TimelineQuerySource],
        *,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        order: Literal["asc", "desc"],
        limit: int,
        offset: int,
    ) -> tuple[list[TimelineRow], int]:
        selects = []
        for source in sources:
            statement = select(
                literal(source.event_type, String).label("event_type"),
                literal(source.rank, Integer).label("rank"),
                source.model.id.label("record_id"),
                source.occurred_at.label("occurred_at"),
                source.model.created_at.label("created_at"),
            ).where(source.model.patient_id == patient_id)
            if source.where is not None:
                statement = statement.where(source.where)
            if occurred_from is not None:
                statement = statement.where(source.occurred_at >= occurred_from)
            if occurred_to is not None:
                statement = statement.where(source.occurred_at <= occurred_to)
            selects.append(statement)
        if not selects:
            return [], 0

        events = union_all(*selects).subquery("events")
        total = self._session.execute(select(func.count()).select_from(events)).scalar_one()

        occurred = events.c.occurred_at.asc() if order == "asc" else events.c.occurred_at.desc()
        rows = self._session.execute(
            select(events.c.event_type, events.c.record_id, events.c.occurred_at)
            # Deterministic: same-instant events always sort by type rank, then insertion
            # time, then id - identically in both directions.
            .order_by(occurred, events.c.rank.asc(), events.c.created_at.asc(), events.c.record_id.asc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [TimelineRow(r.event_type, r.record_id, r.occurred_at) for r in rows], total

    def load(self, model: type, record_ids: list[uuid.UUID], options: tuple = ()) -> dict[uuid.UUID, object]:
        if not record_ids:
            return {}
        records = self._session.execute(select(model).where(model.id.in_(record_ids)).options(*options)).scalars()
        return {record.id: record for record in records}
