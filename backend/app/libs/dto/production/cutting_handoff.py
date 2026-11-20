from pydantic import BaseModel, Field

from app.libs.enums.production import CuttingHandoffFactory


class CuttingHandoffIn(BaseModel):
    production_batch_id: int = Field(gt=0)
    factory: CuttingHandoffFactory
