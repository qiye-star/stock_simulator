"""旧版存档导入接口：POST /import/legacy。业务与校验见 services/legacy_import.py。"""

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.legacy import LegacyImportIn, LegacyImportOut
from stocksim.services import legacy_import as legacy_service

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/legacy", response_model=LegacyImportOut)
def import_legacy(body: LegacyImportIn, user: CurrentUser, db: DbSession) -> LegacyImportOut:
    return legacy_service.import_legacy(db, user, body.content)
