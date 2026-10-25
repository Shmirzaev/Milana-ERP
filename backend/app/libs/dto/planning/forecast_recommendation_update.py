from typing import Literal

from pydantic import BaseModel


RecommendationStatus = Literal["open", "accepted", "dismissed", "converted"]


class ForecastRecommendationPatch(BaseModel):
    status: RecommendationStatus
