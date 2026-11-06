from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.permission_catalog import PERMISSION_KEYS


class FactoryAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: list[str] = Field(default_factory=list, max_length=150)
    deny: list[str] = Field(default_factory=list, max_length=150)

    @model_validator(mode="after")
    def valid_permissions(self):
        self.allow = sorted(set(self.allow))
        self.deny = sorted(set(self.deny))
        unknown = (set(self.allow) | set(self.deny)) - PERMISSION_KEYS
        if unknown:
            raise ValueError(f"Unknown permissions: {sorted(unknown)}")
        if set(self.allow) & set(self.deny):
            raise ValueError("A permission cannot be both allowed and denied")
        return self


AccessPolicy = dict[Literal["MIL", "BST", "ECO"], FactoryAccess]
