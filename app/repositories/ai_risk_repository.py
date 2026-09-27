"""Persistence of stored four-day risk analyses - the AI review pathway (Stage 8)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.schemas import RiskAnalysisListParams, RiskTrigger
from app.models.ai_review import AIRiskAnalysis


class AIRiskAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, analysis: AIRiskAnalysis) -> AIRiskAnalysis:
        self._session.add(analysis)
        self._session.flush()
        return analysis

    def get(self, analysis_id: uuid.UUID, *, for_update: bool = False) -> AIRiskAnalysis | None:
        statement = select(AIRiskAnalysis).where(AIRiskAnalysis.id == analysis_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def list(self, params: RiskAnalysisListParams) -> tuple[list[AIRiskAnalysis], int]:
        conditions = []
        if params.patient_id is not None:
            conditions.append(AIRiskAnalysis.patient_id == params.patient_id)
        if params.review_status is not None:
            conditions.append(AIRiskAnalysis.review_status == params.review_status.value)
        total = self._session.execute(select(func.count()).select_from(AIRiskAnalysis).where(*conditions)).scalar_one()
        items = self._session.execute(
            select(AIRiskAnalysis).where(*conditions)
            .order_by(AIRiskAnalysis.created_at.desc(), AIRiskAnalysis.id)
            .limit(params.limit).offset(params.offset)
        ).scalars().all()
        return list(items), total

    def event_triggered_since(self, patient_id: uuid.UUID, since: datetime) -> bool:
        """Cooldown check for event-triggered analyses of one patient."""
        return self._session.execute(
            select(AIRiskAnalysis.id).where(AIRiskAnalysis.patient_id == patient_id,
                                            AIRiskAnalysis.trigger == RiskTrigger.EVENT.value,
                                            AIRiskAnalysis.created_at >= since).limit(1)
        ).first() is not None
