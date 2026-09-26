"""The authenticated caller, resolved once per request (Stage 5).

Authorization decisions use only `permissions` (code -> broadest scope held through the
user's ACTIVE roles). No code checks role names.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.permissions import P, Scope


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID | None
    staff_id: uuid.UUID | None
    username: str
    permissions: Mapping[str, Scope] = field(default_factory=dict)
    is_superuser: bool = False
    session_id: uuid.UUID | None = None
    role_ids: frozenset[uuid.UUID] = frozenset()

    def has(self, permission: P | str) -> bool:
        return self.is_superuser or str(permission) in self.permissions

    def scope(self, permission: P | str) -> Scope | None:
        if self.is_superuser:
            return Scope.ALL
        return self.permissions.get(str(permission))

    def own_staff_filter(self, permission: P | str) -> uuid.UUID | None:
        """Staff id to restrict records to for an OWN-scoped permission; None means unrestricted.

        A principal with only OWN scope but no staff member gets a random id, so nothing matches.
        """
        if self.scope(permission) == Scope.OWN:
            return self.staff_id or uuid.uuid4()
        return None
