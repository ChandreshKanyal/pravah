from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GridSpec:
    crs: str  # "EPSG:32644"
    x0: float  # upper-left x (m)
    y0: float  # upper-left y (m)
    cell: float  # 30.0
    width: int  # columns
    height: int  # rows
    # affine: x = x0 + col*cell ; y = y0 - row*cell

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GridSpec":
        return cls(**d)
