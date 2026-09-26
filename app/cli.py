"""Administrative command line (Stage 5).

Create the first administrator (or another superuser) for the configured DATABASE_URL:

    python -m app.cli create-admin --username admin --employee-code ADM-0001 \
        --first-name Grace --last-name Hopper

The password is read from the HMS_ADMIN_PASSWORD environment variable if set, otherwise
prompted for twice (not echoed). It is never accepted as a command-line argument, so it
does not end up in shell history or process listings.

If the staff member does not exist it is created (designation ADMINISTRATOR) in an
"Administration" department, which is created if needed. The user receives SUPER_ADMIN.
"""

import argparse
import getpass
import os
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import ConfigurationError, get_settings
from app.core.permissions import SUPER_ADMIN
from app.core.security import check_password_policy, hash_password
from app.db.session import build_engine, build_session_factory
from app.models.auth import User, UserRole
from app.models.staff import Department, Designation, RecordStatus, Staff
from app.repositories.auth_repository import RoleRepository, UserRepository
from app.repositories.staff_repository import DepartmentRepository, StaffRepository
from app.schemas.auth import Username
from app.schemas.staff import EmployeeCode

ADMIN_DEPARTMENT = "Administration"
PASSWORD_ENV = "HMS_ADMIN_PASSWORD"


def _read_password(username: str) -> str:
    password = os.environ.get(PASSWORD_ENV)
    if password is None:
        password = getpass.getpass("New admin password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Passwords do not match.")
    try:
        check_password_policy(password, username=username)
    except ValueError as exc:
        raise SystemExit(f"Password rejected: {exc}") from None
    return password


def create_admin(session: Session, *, username: str, employee_code: str, first_name: str, last_name: str,
                 password: str) -> User:
    users, staff_repo = UserRepository(session), StaffRepository(session)
    role = RoleRepository(session).by_name(SUPER_ADMIN)
    if role is None:
        raise SystemExit("SUPER_ADMIN role not found; run `alembic upgrade head` first.")
    if users.by_username(username) is not None:
        raise SystemExit(f"Username {username} already exists.")
    staff = staff_repo.by_employee_code(employee_code)
    if staff is None:
        departments = DepartmentRepository(session)
        department = departments.by_name(ADMIN_DEPARTMENT)
        if department is None:
            department = departments.add(Department(name=ADMIN_DEPARTMENT, status=RecordStatus.ACTIVE.value,
                                                    description="Hospital administration"))
        staff = staff_repo.add(Staff(employee_code=employee_code, first_name=first_name, last_name=last_name,
                                     designation=Designation.ADMINISTRATOR.value, department_id=department.id,
                                     status=RecordStatus.ACTIVE.value))
    elif users.by_staff_id(staff.id) is not None:
        raise SystemExit(f"Staff member {employee_code} already has a user account.")
    user = users.add(User(staff_id=staff.id, username=username, password_hash=hash_password(password),
                          status=RecordStatus.ACTIVE.value, password_changed_at=utc_now()))
    users.add_assignment(UserRole(user_id=user.id, role_id=role.id))
    session.commit()
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create a SUPER_ADMIN user")
    admin.add_argument("--username", required=True)
    admin.add_argument("--employee-code", required=True)
    admin.add_argument("--first-name", default="System")
    admin.add_argument("--last-name", default="Administrator")
    args = parser.parse_args(argv)

    try:
        username = TypeAdapter(Username).validate_python(args.username)
        employee_code = TypeAdapter(EmployeeCode).validate_python(args.employee_code)
    except ValidationError as exc:
        raise SystemExit(f"Invalid argument: {exc.errors()[0]['msg']}") from None
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2
    password = _read_password(username)
    engine = build_engine(settings)
    try:
        with build_session_factory(engine)() as session:
            user = create_admin(session, username=username, employee_code=employee_code,
                                first_name=args.first_name, last_name=args.last_name, password=password)
    finally:
        engine.dispose()
    print(f"Created SUPER_ADMIN user '{user.username}' for staff {employee_code}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
