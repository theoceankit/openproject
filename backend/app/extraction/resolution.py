import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Person, Project, ProjectResolution, Team, Term, Topic
from app.extraction.prompts import RESOLUTION_SYSTEM_PROMPT, build_resolution_prompt
from app.extraction.schemas import ExtractedProject, ProjectResolutionResult
from app.providers.base import ModelProvider

logger = logging.getLogger("app.extraction")


async def resolve_project(
    db: AsyncSession,
    provider: ModelProvider,
    document_id: uuid.UUID,
    candidate: ExtractedProject,
    existing_project_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, str]:
    """Resolve an extracted project against existing projects.

    Returns (project_id, outcome), where outcome is "match", "new", or "ambiguous".
    On "ambiguous", project_id is None and a ProjectResolution row is created for
    later user confirmation.

    `existing_project_id` is the document's current project_id, if it was already resolved by a
    prior extraction; re-extraction then keeps that assignment instead of re-deriving it (and
    risking a different, non-deterministic outcome from the same LLM resolution call for
    unchanged candidate/existing-projects input).
    """
    existing = (await db.execute(select(Project))).scalars().all()

    if existing_project_id is not None and any(p.id == existing_project_id for p in existing):
        logger.info(
            "project resolution for %r: match (sticky to document's existing project_id=%s)",
            candidate.name,
            existing_project_id,
        )
        return existing_project_id, "match"

    if not existing:
        project = Project(name=candidate.name, description=candidate.description or None)
        db.add(project)
        await db.flush()
        logger.info("project resolution for %r: new (no existing projects), project_id=%s", candidate.name, project.id)
        return project.id, "new"

    candidate_payload = {"name": candidate.name, "description": candidate.description}
    existing_payload = [{"id": str(p.id), "name": p.name, "description": p.description or ""} for p in existing]

    response = await provider.generate(
        build_resolution_prompt(candidate_payload, existing_payload),
        system=RESOLUTION_SYSTEM_PROMPT,
        format=ProjectResolutionResult.model_json_schema(),
        call_site="project_resolution",
    )
    result = ProjectResolutionResult.model_validate_json(response)

    if result.outcome == "match" and result.project_id:
        existing_ids = {p.id for p in existing}
        try:
            matched_id = uuid.UUID(result.project_id)
        except ValueError:
            matched_id = None
        if matched_id in existing_ids:
            logger.info("project resolution for %r: match, project_id=%s", candidate.name, matched_id)
            return matched_id, "match"
        logger.warning(
            "project resolution for %r: LLM returned match with unrecognized project_id=%r, degrading to ambiguous",
            candidate.name,
            result.project_id,
        )
        result = ProjectResolutionResult(outcome="ambiguous", candidate_ids=[str(p.id) for p in existing])

    if result.outcome == "new":
        existing_by_name = (
            await db.execute(
                select(Project).where(func.lower(Project.name) == candidate.name.lower())
            )
        ).scalar_one_or_none()
        if existing_by_name:
            logger.info(
                "project resolution for %r: new (matched by name to existing), project_id=%s",
                candidate.name,
                existing_by_name.id,
            )
            return existing_by_name.id, "match"
        project = Project(name=candidate.name, description=candidate.description or None)
        db.add(project)
        await db.flush()
        logger.info("project resolution for %r: new, project_id=%s", candidate.name, project.id)
        return project.id, "new"

    db.add(
        ProjectResolution(
            document_id=document_id,
            candidate_name=candidate.name,
            candidate_description=candidate.description or None,
            candidate_project_ids=[uuid.UUID(cid) for cid in result.candidate_ids],
        )
    )
    logger.info(
        "project resolution for %r: ambiguous, candidate_ids=%s, document_id=%s",
        candidate.name,
        result.candidate_ids,
        document_id,
    )
    return None, "ambiguous"


async def _resolve_unique(db: AsyncSession, model, query, name: str):
    """Like scalar_one_or_none(), but picks one deterministically instead of raising on duplicates."""
    rows = (await db.execute(query.order_by(model.created_at, model.id))).scalars().all()
    if len(rows) > 1:
        logger.warning(
            "multiple %s rows named %r found, picking id=%s", model.__tablename__, name, rows[0].id
        )
    return rows[0] if rows else None


async def resolve_entity_ref(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    name: str,
    local_entities: dict[str, tuple[str, uuid.UUID]],
    document_id: uuid.UUID | None,
) -> tuple[str, uuid.UUID]:
    """Resolve the subject or object of a relation to an entity type and id.

    Checks entities created earlier in this extraction pass, then existing Person/Team
    rows for the project and existing Projects by name, then falls back to finding or
    creating a Topic.
    """
    if name in local_entities:
        return local_entities[name]

    if project_id is not None:
        for model, type_name in ((Person, "person"), (Team, "team")):
            row = await _resolve_unique(
                db, model, select(model).where(model.project_id == project_id, model.name == name), name
            )
            if row:
                return type_name, row.id

    project = await _resolve_unique(db, Project, select(Project).where(Project.name == name), name)
    if project:
        return "project", project.id

    topic_query = select(Topic).where(Topic.name == name)
    topic_query = topic_query.where(
        Topic.project_id == project_id if project_id is not None else Topic.project_id.is_(None)
    )
    topic = await _resolve_unique(db, Topic, topic_query, name)
    if topic:
        return "topic", topic.id

    topic = Topic(project_id=project_id, document_id=document_id, name=name)
    db.add(topic)
    await db.flush()
    return "topic", topic.id


async def apply_resolution(
    db: AsyncSession, resolution: ProjectResolution, project_id: uuid.UUID | None
) -> uuid.UUID:
    """Apply a user's confirmation of a pending ProjectResolution.

    If project_id is given, attaches the document to that existing project; otherwise
    creates a new project from the resolution's candidate name and description. Backfills
    project_id on the document and on any entities extracted while the resolution was
    pending (which were left unscoped, with project_id unset).
    """
    if project_id is None:
        existing = (
            await db.execute(
                select(Project).where(func.lower(Project.name) == resolution.candidate_name.lower())
            )
        ).scalar_one_or_none()
        if existing:
            project_id = existing.id
        else:
            project = Project(name=resolution.candidate_name, description=resolution.candidate_description or None)
            db.add(project)
            await db.flush()
            project_id = project.id

    document = (await db.execute(select(Document).where(Document.id == resolution.document_id))).scalar_one()
    document.project_id = project_id

    for model in (Term, Team, Person, Topic):
        await db.execute(
            update(model)
            .where(model.document_id == resolution.document_id, model.project_id.is_(None))
            .values(project_id=project_id)
        )

    resolution.status = "resolved"
    resolution.resolved_project_id = project_id
    return project_id
