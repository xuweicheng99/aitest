from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import get_test_plan_service
from app.core.exceptions import InvalidRequestError
from app.schemas.test_plan import PlanExecuteRequest, PlanExecutionResponse, TestPlan
from app.services.document_service import MAX_DOCUMENT_BYTES, DocumentError, DocumentService
from app.services.test_plan_service import TestPlanService


router = APIRouter(prefix="/plans", tags=["test plans"])


@router.post("/generate", response_model=TestPlan)
async def generate_plan(
    requirements_text: str = Form(default=""),
    max_cases: int = Form(default=10, ge=1, le=30),
    document: UploadFile | None = File(default=None),
    service: TestPlanService = Depends(get_test_plan_service),
) -> TestPlan:
    try:
        if document is not None and document.filename:
            content = await document.read(MAX_DOCUMENT_BYTES + 1)
            requirements = DocumentService.extract(document.filename, content)
            source_name = document.filename
        else:
            requirements = requirements_text.strip()
            if len(requirements) < 10:
                raise DocumentError("请上传需求文档或输入至少 10 个字的需求")
            if len(requirements) > 60_000:
                raise DocumentError("需求内容不能超过 6 万字")
            source_name = "手动输入需求"
    except DocumentError as exc:
        raise InvalidRequestError(str(exc)) from exc
    finally:
        if document is not None:
            await document.close()
    return await service.generate(
        requirements=requirements,
        source_name=source_name,
        max_cases=max_cases,
    )


@router.post("/execute", response_model=PlanExecutionResponse)
async def execute_plan(
    request: PlanExecuteRequest,
    service: TestPlanService = Depends(get_test_plan_service),
) -> PlanExecutionResponse:
    return await service.execute(request)
