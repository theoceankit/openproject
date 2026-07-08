from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page
from app.db.models import Project
from app.db.session import get_db

router = APIRouter(prefix="/projects")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectOut]:
    total = (await db.execute(select(func.count()).select_from(Project))).scalar_one()
    projects = (
        await db.execute(select(Project).order_by(Project.name).limit(limit).offset(offset))
    ).scalars().all()
    return Page(
        items=[ProjectOut(id=str(p.id), name=p.name, description=p.description) for p in projects],
        total=total,
    )
