import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Fact, Person, Project, Team, Topic
from app.extraction.resolution import resolve_entity_ref
from app.extraction.schemas import FactUpdateResult

_ENTITY_MODELS = {
    "person": Person,
    "team": Team,
    "project": Project,
    "topic": Topic,
}


async def resolve_project_by_name(db: AsyncSession, name: str) -> Project | None:
    """Find an existing project by case-insensitive exact name match."""
    name = name.strip()
    if not name:
        return None

    return (
        await db.execute(select(Project).where(func.lower(Project.name) == name.lower()))
    ).scalar_one_or_none()


async def record_fact(db: AsyncSession, update: FactUpdateResult, source_message_id: uuid.UUID) -> Fact | None:
    """Record a fact extracted from a chat message, if it asserts anything worth keeping."""
    if not update.should_record or not update.subject.strip() or not update.predicate.strip():
        return None

    project = await resolve_project_by_name(db, update.project)
    project_id = project.id if project else None

    subject_type, subject_id = await resolve_entity_ref(db, project_id, update.subject.strip(), {}, document_id=None)

    object_project_id = project_id
    if object_project_id is None and subject_type == "project":
        object_project_id = subject_id

    object_type: str | None = None
    object_id: uuid.UUID | None = None
    if update.object.strip():
        object_type, object_id = await resolve_entity_ref(
            db, object_project_id, update.object.strip(), {}, document_id=None
        )

    value = update.value.strip() or None

    if object_type is None and value is None:
        return None

    duplicate = (
        await db.execute(
            select(Fact).where(
                Fact.subject_type == subject_type,
                Fact.subject_id == subject_id,
                Fact.predicate == update.predicate.strip(),
                Fact.object_type == object_type,
                Fact.object_id == object_id,
                Fact.value == value,
                Fact.status.in_(("pending", "confirmed")),
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return None

    fact = Fact(
        subject_type=subject_type,
        subject_id=subject_id,
        predicate=update.predicate.strip(),
        object_type=object_type,
        object_id=object_id,
        value=value,
        source_type="message",
        source_id=source_message_id,
        status="pending",
    )
    db.add(fact)
    await db.flush()
    return fact


async def describe_fact(db: AsyncSession, fact: Fact) -> dict:
    """Build a display-friendly description of a Fact for confirmation UI."""
    subject = await _display_name(db, fact.subject_type, fact.subject_id)
    if fact.object_type is not None and fact.object_id is not None:
        obj = await _display_name(db, fact.object_type, fact.object_id)
    else:
        obj = fact.value or ""

    return {
        "id": str(fact.id),
        "subject": subject,
        "predicate": fact.predicate,
        "object": obj,
    }


async def resolve_fact(db: AsyncSession, fact: Fact, confirm: bool) -> Fact:
    """Apply a user's confirmation or rejection of a pending Fact."""
    fact.status = "confirmed" if confirm else "rejected"
    return fact


async def _display_name(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> str:
    model = _ENTITY_MODELS.get(entity_type)
    if model is None:
        return str(entity_id)

    row = (await db.execute(select(model).where(model.id == entity_id))).scalar_one_or_none()
    return row.name if row is not None else str(entity_id)


async def build_known_facts_block(db: AsyncSession, query: str) -> str | None:
    """Build a "Known facts" prompt section from recorded Facts relevant to the query."""
    facts = (
        await db.execute(
            select(Fact)
            .where(Fact.status == "confirmed")
            .order_by(Fact.subject_type, Fact.subject_id, Fact.predicate, Fact.created_at)
        )
    ).scalars().all()

    if not facts:
        return None

    groups: list[list[Fact]] = []
    for fact in facts:
        if groups and (
            groups[-1][-1].subject_type == fact.subject_type
            and groups[-1][-1].subject_id == fact.subject_id
            and groups[-1][-1].predicate == fact.predicate
        ):
            groups[-1].append(fact)
        else:
            groups.append([fact])

    query_lower = query.lower()
    lines: list[str] = []
    for group in groups:
        subject_name = await _display_name(db, group[0].subject_type, group[0].subject_id)
        predicate = group[0].predicate

        if subject_name.lower() not in query_lower and predicate.lower() not in query_lower:
            continue

        displayed_values = []
        for fact in group:
            if fact.object_type is not None and fact.object_id is not None:
                displayed_values.append(await _display_name(db, fact.object_type, fact.object_id))
            else:
                displayed_values.append(fact.value or "")

        if len(group) == 1:
            lines.append(f"{subject_name} {predicate}: {displayed_values[0]}")
        else:
            history = "; ".join(
                f"{fact.created_at.strftime('%Y-%m-%d')}: {displayed_value}"
                for fact, displayed_value in zip(group, displayed_values)
            )
            lines.append(
                f"{subject_name} {predicate} history (most recent last): {history}"
            )

    if not lines:
        return None

    return "Known facts (current values; use these instead of any conflicting numbered context entry):\n" + "\n".join(
        lines
    )
