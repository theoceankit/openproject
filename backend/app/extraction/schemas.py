from typing import Literal

from pydantic import BaseModel, Field


class ExtractedProject(BaseModel):
    name: str
    description: str = ""


class ExtractedPerson(BaseModel):
    name: str
    role: str = ""


class ExtractedTerm(BaseModel):
    term: str
    definition: str


class ExtractedTeam(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)


class ExtractedRelation(BaseModel):
    subject: str
    relation: str
    object: str


class ExtractionResult(BaseModel):
    """Output of a single extraction pass over one document."""

    project: ExtractedProject
    people: list[ExtractedPerson] = Field(default_factory=list)
    terms: list[ExtractedTerm] = Field(default_factory=list)
    teams: list[ExtractedTeam] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


class ProjectResolutionResult(BaseModel):
    """Outcome of comparing an extracted project against existing projects."""

    outcome: Literal["match", "new", "ambiguous"]
    project_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class FactUpdateResult(BaseModel):
    """Outcome of checking the user's latest chat message for a fact worth recording."""

    should_record: bool
    project: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    value: str = ""
