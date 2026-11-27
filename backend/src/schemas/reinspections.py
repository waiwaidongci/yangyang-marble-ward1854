from pydantic import BaseModel, ConfigDict, Field


class ReinspectionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    tone_deviation_min: float = Field(ge=-20, le=20)
    tone_deviation_max: float = Field(ge=-20, le=20)
    note: str = Field(min_length=4, max_length=1000)


class ReinspectionInfo(BaseModel):
    id: int
    run_id: int
    version: int
    tone_deviation_min: float
    tone_deviation_max: float
    scenario_count: int
    robust_kit_count: int
    removed_kit_count: int
    note: str
    created_at: str
