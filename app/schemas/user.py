from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    full_name: str
    role: str
    password: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
