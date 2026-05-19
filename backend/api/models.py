"""
api/models.py — Pydantic request/response models
"""
from pydantic import BaseModel
from typing import Optional


class SiteConfirmRequest(BaseModel):
    lat: float
    lon: float
    units: str = "F"           # "F" or "C"
    acf: float = 1.0           # annual correction factor (1% default = ACF 99)


class StationsRequest(BaseModel):
    lat: float
    lon: float
    elevation_m: float = 0.0


class AvailabilityRequest(BaseModel):
    station_id: str
    year_start: int = 2000
    year_end: int = 2025


class FetchRequest(BaseModel):
    station_id: str
    years: list[int]
    units: str = "F"


class ProcessRequest(BaseModel):
    station_id: str
    years: list[int]
    units: str = "F"
    lat: float
    lon: float
    elevation_m: float = 0.0
    filter_type: Optional[str] = None      # e.g. "TYPE_3H", "FM-15"
    exclude_quality_codes: list[str] = ["2", "3"]
    clip_lower_f: float = 5.0
    clip_upper_f: Optional[float] = None


class DesignConditionsRequest(BaseModel):
    lat: float
    lon: float
    units: str = "F"
    acf: float = 1.0
    year_start: int = 2000
    year_end: int = 2024
