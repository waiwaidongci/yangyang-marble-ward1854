from fastapi import APIRouter

from src.controllers.dependencies import Admin, Db
from src.schemas.reinspections import ReinspectionCreate, ReinspectionInfo
from src.services import reinspections

router = APIRouter(prefix='/runs/{run_id}/reinspections')


@router.get('', response_model=list[ReinspectionInfo])
def versions(run_id: int, session: Db, actor: Admin):
    return [reinspections.serialize(entry) for entry in reinspections.list_versions(session, run_id)]


@router.post('', response_model=ReinspectionInfo, status_code=201)
def record(run_id: int, payload: ReinspectionCreate, session: Db, actor: Admin):
    return reinspections.add_reinspection(session, run_id, payload, actor)
