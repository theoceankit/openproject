import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Chunk, Document, Person, Relation, Team, Term, Topic
from app.extraction.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_prompt
from app.extraction.resolution import resolve_entity_ref, resolve_project
from app.extraction.schemas import ExtractionResult
from app.model_settings.service import resolve_model
from app.providers.base import ModelProvider

logger = logging.getLogger("app.extraction")


@dataclass
class ExtractionOutcome:
    """Result of running extraction over a document and persisting its entities."""

    project_id: uuid.UUID | None
    project_resolution: str
    result: ExtractionResult


async def extract_document(db: AsyncSession, provider: ModelProvider, document: Document) -> ExtractionOutcome:
    """Run LLM extraction over a document's chunks and persist the resulting entities."""
    chunks = (
        (await db.execute(select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)))
        .scalars()
        .all()
    )
    sections = _truncate_sections([(chunk.section, chunk.content) for chunk in chunks], settings.extraction_max_chars)
    model = await resolve_model(db, "extraction")

    response = await provider.generate(
        build_extraction_prompt(document.path, sections),
        system=EXTRACTION_SYSTEM_PROMPT,
        format=ExtractionResult.model_json_schema(),
        model=model,
        call_site="extraction",
    )
    result = ExtractionResult.model_validate_json(response)

    await _clear_prior_extraction(db, document.id)

    project_id, project_resolution = await resolve_project(
        db, provider, document.id, result.project, existing_project_id=document.project_id, model=model
    )
    document.project_id = project_id

    local_entities: dict[str, tuple[str, uuid.UUID]] = {}
    if project_id is not None:
        local_entities[result.project.name] = ("project", project_id)

    team_ids: dict[str, uuid.UUID] = {}
    for team in result.teams:
        row = Team(project_id=project_id, document_id=document.id, name=team.name)
        db.add(row)
        await db.flush()
        team_ids[team.name] = row.id
        local_entities[team.name] = ("team", row.id)

    member_team: dict[str, uuid.UUID] = {}
    for team in result.teams:
        for member in team.members:
            member_team[member] = team_ids[team.name]

    for person in result.people:
        row = Person(
            project_id=project_id,
            team_id=member_team.get(person.name),
            document_id=document.id,
            name=person.name,
            role=person.role or None,
        )
        db.add(row)
        await db.flush()
        local_entities[person.name] = ("person", row.id)

    for term in result.terms:
        db.add(Term(project_id=project_id, document_id=document.id, term=term.term, definition=term.definition))

    for relation in result.relations:
        subject_type, subject_id = await resolve_entity_ref(db, project_id, relation.subject, local_entities, document.id)
        object_type, object_id = await resolve_entity_ref(db, project_id, relation.object, local_entities, document.id)
        db.add(
            Relation(
                subject_type=subject_type,
                subject_id=subject_id,
                relation_label=relation.relation,
                object_type=object_type,
                object_id=object_id,
                document_id=document.id,
            )
        )

    await db.commit()
    logger.info(
        "extraction for document %s: project_resolution=%s project_id=%s people=%d teams=%d terms=%d relations=%d",
        document.id,
        project_resolution,
        project_id,
        len(result.people),
        len(result.teams),
        len(result.terms),
        len(result.relations),
    )
    return ExtractionOutcome(project_id=project_id, project_resolution=project_resolution, result=result)


async def _clear_prior_extraction(db: AsyncSession, document_id: uuid.UUID) -> None:
    await db.execute(delete(Relation).where(Relation.document_id == document_id))
    await db.execute(delete(Person).where(Person.document_id == document_id))
    await db.execute(delete(Team).where(Team.document_id == document_id))
    await db.execute(delete(Term).where(Term.document_id == document_id))
    await db.execute(delete(Topic).where(Topic.document_id == document_id))


def _truncate_sections(sections: list[tuple[str | None, str]], max_chars: int) -> list[tuple[str | None, str]]:
    """Keep sections in order until the combined content reaches max_chars, truncating the last one."""
    result: list[tuple[str | None, str]] = []
    remaining = max_chars
    for section, content in sections:
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[:remaining]
        result.append((section, content))
        remaining -= len(content)
    return result
