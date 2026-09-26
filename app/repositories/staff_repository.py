"""Data access for departments and staff. No business rules and no commits."""

import re
import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.staff import Department, Staff

_LIKE_SPECIAL = re.compile(r"([\\%_])")


def contains_pattern(value: str) -> str:
    return "%" + _LIKE_SPECIAL.sub(lambda m: "\\" + m.group(1), value) + "%"


class BaseRepository:
    model: type

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, record_id: uuid.UUID, *, for_update: bool = False):
        statement = select(self.model).where(self.model.id == record_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, record):
        self._session.add(record)
        self._session.flush()
        return record

    def _page(self, statement: Select, order_by: tuple, limit: int, offset: int) -> tuple[list, int]:
        total = self._session.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        items = self._session.execute(statement.order_by(*order_by).limit(limit).offset(offset)).scalars().all()
        return list(items), total

    def _filtered(self, filters: dict[str, Any]) -> Select:
        statement = select(self.model)
        for name, value in filters.items():
            if value is not None:
                statement = statement.where(getattr(self.model, name) == value)
        return statement


class DepartmentRepository(BaseRepository):
    model = Department

    def by_name(self, name: str, *, exclude_id: uuid.UUID | None = None) -> Department | None:
        statement = select(Department).where(func.lower(Department.name) == name.lower())
        if exclude_id is not None:
            statement = statement.where(Department.id != exclude_id)
        return self._session.execute(statement).scalar_one_or_none()

    def search(self, *, status, q: str | None, limit: int, offset: int) -> tuple[list[Department], int]:
        statement = self._filtered({"status": status})
        if q:
            statement = statement.where(Department.name.ilike(contains_pattern(q), escape="\\"))
        return self._page(statement, (func.lower(Department.name), Department.id), limit, offset)


class StaffRepository(BaseRepository):
    model = Staff

    def by_employee_code(self, code: str) -> Staff | None:
        return self._session.execute(select(Staff).where(Staff.employee_code == code)).scalar_one_or_none()

    def by_email(self, email: str, *, exclude_id: uuid.UUID | None = None) -> Staff | None:
        statement = select(Staff).where(func.lower(Staff.email) == email.lower())
        if exclude_id is not None:
            statement = statement.where(Staff.id != exclude_id)
        return self._session.execute(statement).scalar_one_or_none()

    def search(self, *, filters: dict[str, Any], q: str | None, limit: int, offset: int) -> tuple[list[Staff], int]:
        statement = self._filtered(filters)
        if q:
            pattern = contains_pattern(q)
            statement = statement.where(
                or_(
                    Staff.employee_code.ilike(pattern, escape="\\"),
                    Staff.first_name.ilike(pattern, escape="\\"),
                    Staff.last_name.ilike(pattern, escape="\\"),
                    func.concat_ws(" ", Staff.first_name, Staff.last_name).ilike(pattern, escape="\\"),
                )
            )
        order = (func.lower(Staff.last_name), func.lower(Staff.first_name), Staff.employee_code)
        return self._page(statement, order, limit, offset)
