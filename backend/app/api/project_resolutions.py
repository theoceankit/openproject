import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page
from app.db.models import Document, Project, ProjectResolution
from app.db.session import get_db
from app.extraction.resolution import apply_resolution

router = APIRouter(prefix="/project-resolutions")


class ProjectResolutionOut(BaseModel):
    id: str
    document_id: str
    document_path: str
    candidate_name: str
    candidate_description: str | None = None
    candidate_project_ids: list[str]
    status: str


class ResolveRequest(BaseModel):
    project_id: str | None = None


class ResolveResult(BaseModel):
    project_id: str
    status: str


@router.get("", response_model=Page[ProjectResolutionOut])
async def list_project_resolutions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectResolutionOut]:
    total = (
        await db.execute(
            select(func.count()).select_from(ProjectResolution).where(ProjectResolution.status == "pending")
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(ProjectResolution, Document)
            .join(Document, ProjectResolution.document_id == Document.id)
            .where(ProjectResolution.status == "pending")
            .order_by(ProjectResolution.created_at)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(
        items=[
            ProjectResolutionOut(
                id=str(resolution.id),
                document_id=str(resolution.document_id),
                document_path=document.path,
                candidate_name=resolution.candidate_name,
                candidate_description=resolution.candidate_description,
                candidate_project_ids=[str(cid) for cid in resolution.candidate_project_ids],
                status=resolution.status,
            )
            for resolution, document in rows
        ],
        total=total,
    )


@router.post("/{resolution_id}/resolve", response_model=ResolveResult)
async def resolve_project_resolution(
    resolution_id: str, request: ResolveRequest, db: AsyncSession = Depends(get_db)
) -> ResolveResult:
    try:
        resolution = (
            await db.execute(select(ProjectResolution).where(ProjectResolution.id == uuid.UUID(resolution_id)))
        ).scalar_one_or_none()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project resolution id")
    if resolution is None:
        raise HTTPException(status_code=404, detail="Project resolution not found")
    if resolution.status != "pending":
        raise HTTPException(status_code=400, detail="Project resolution is not pending")

    project_id: uuid.UUID | None = None
    if request.project_id is not None:
        try:
            project_id = uuid.UUID(request.project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project id")
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

    resolved_project_id = await apply_resolution(db, resolution, project_id)
    await db.commit()
    return ResolveResult(project_id=str(resolved_project_id), status="resolved")
