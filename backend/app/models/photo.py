"""S12 photo classification schemas (SPEC S12.2)."""
from typing import Literal

from pydantic import BaseModel, Field


class BuildingPhotoResult(BaseModel):
    building_visible: bool
    structure_class: Literal["pukka_multi_storey", "pukka_low_rise", "kaccha", "makeshift_or_hut", "informal_cluster", "unclear"]
    wall_material: Literal["rcc_or_brick_cement", "brick_mud", "stone_mud", "wood", "tin_or_sheet", "tarpaulin_or_plastic",
                           "mixed", "unclear"]
    roof_material: Literal["rcc_slab", "tin_or_sheet", "tile", "thatch", "tarpaulin", "unclear"]
    storeys_estimate: int | None = None
    visible_risk_notes: list[str] = Field(default_factory=list, description='e.g. "built on slope edge", "next to stream bank"')
    confidence: float = Field(description="0..1")
    rationale: str = Field(description="at most 40 words")


class DrainPhotoResult(BaseModel):
    drain_visible: bool
    condition: Literal["clear", "partially_blocked", "blocked", "unclear"]
    blockage_types: list[Literal["garbage", "silt", "vegetation", "construction_debris", "other"]] = Field(default_factory=list)
    confidence: float = Field(description="0..1")
    rationale: str = Field(description="at most 40 words")


# photo class -> building class used by the exposure engine (S6.3); labelled "verified", never "likely"
PHOTO_TO_BUILDING = {
    "pukka_multi_storey": "verified_pukka_multi_storey",
    "pukka_low_rise": "verified_pukka_low_rise",
    "kaccha": "verified_kaccha",
    "makeshift_or_hut": "verified_makeshift_or_hut",
    "informal_cluster": "verified_informal_cluster",
}
