from dataclasses import dataclass
from typing import Dict, Optional
import uuid


@dataclass
class MemoryUser:
    id: str
    email: str
    full_name: str
    role: str
    password_hash: str


class MemoryStore:
    def __init__(self) -> None:
        self._users: Dict[str, MemoryUser] = {}
        self._users_by_email: Dict[str, MemoryUser] = {}

    def create_user(self, email: str, full_name: str, role: str, password_hash: str) -> MemoryUser:
        if email in self._users_by_email:
            raise ValueError("email_exists")
        user = MemoryUser(
            id=str(uuid.uuid4()),
            email=email,
            full_name=full_name,
            role=role,
            password_hash=password_hash,
        )
        self._users[user.id] = user
        self._users_by_email[email] = user
        return user

    def get_user(self, user_id: str) -> Optional[MemoryUser]:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> Optional[MemoryUser]:
        return self._users_by_email.get(email)


memory_store = MemoryStore()
