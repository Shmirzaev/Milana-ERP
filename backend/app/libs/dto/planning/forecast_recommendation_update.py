from pydantic import BaseModel

from app.libs.enums.planning import ForecastRecommendationStatus


class ForecastRecommendationPatch(BaseModel):
    status: ForecastRecommendationStatus
