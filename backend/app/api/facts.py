import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page
from app.chat.memory import describe_fact, resolve_fact
from app.db.models import Fact
from app.db.session import get_db

router = APIRouter(prefix="/facts")


class PendingFactOut(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str


class ResolveFactRequest(BaseModel):
    confirm: bool


class ResolveFactResult(BaseModel):
    id: str
    status: str


@router.get("/pending", response_model=Page[PendingFactOut])
async def list_pending_facts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[PendingFactOut]:
    total = (
        await db.execute(select(func.count()).select_from(Fact).where(Fact.status == "pending"))
    ).scalar_one()
    facts = (
        await db.execute(
            select(Fact).where(Fact.status == "pending").order_by(Fact.created_at).limit(limit).offset(offset)
        )
    ).scalars().all()
    return Page(items=[PendingFactOut(**await describe_fact(db, fact)) for fact in facts], total=total)


@router.post("/{fact_id}/resolve", response_model=ResolveFactResult)
async def resolve_pending_fact(
    fact_id: str, request: ResolveFactRequest, db: AsyncSession = Depends(get_db)
) -> ResolveFactResult:
    try:
        fact = (await db.execute(select(Fact).where(Fact.id == uuid.UUID(fact_id)))).scalar_one_or_none()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid fact id")
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    if fact.status != "pending":
        raise HTTPException(status_code=400, detail="Fact is not pending")

    fact = await resolve_fact(db, fact, request.confirm)
    await db.commit()
    return ResolveFactResult(id=str(fact.id), status=fact.status)
