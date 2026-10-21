
from typing import Literal

from pydantic import BaseModel, Field


ExperienceLevel = Literal[
    "any",
    "intern",
    "junior",
    "mid",
    "senior"
]

ContractType = Literal[
    "any",
    "internship",
    "full_time",
    "part_time",
    "contract"
]


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)

    skills: list[str] = Field(default_factory=list)

    target_roles: list[str] = Field(default_factory=list)

    experience_level: ExperienceLevel = "any"

    contract_type: ContractType = "any"

    preferred_location: str = Field(
        default="",
        max_length=150
    )


class ProfileUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150
    )

    skills: list[str] | None = None

    target_roles: list[str] | None = None

    experience_level: ExperienceLevel | None = None

    contract_type: ContractType | None = None

    preferred_location: str | None = Field(
        default=None,
        max_length=150
    )
