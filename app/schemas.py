"""Pydantic 响应模型"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class RegionOut(BaseModel):
    id: int
    city: str
    district: str
    code: str

    class Config:
        from_attributes = True


class CommunityOut(BaseModel):
    id: int
    region_id: int
    name: str
    address: Optional[str] = None
    area_name: Optional[str] = None
    market_type: Optional[str] = None
    property_type: Optional[str] = None
    developer: Optional[str] = None
    build_year: Optional[int] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    region_code: Optional[str] = None
    region_district: Optional[str] = None

    class Config:
        from_attributes = True


class ListingOut(BaseModel):
    id: int
    community_id: Optional[int] = None
    region_id: int
    listing_type: str
    market_type: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    unit_price: Optional[float] = None
    area: Optional[float] = None
    rooms: Optional[str] = None
    floor: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TransactionOut(BaseModel):
    id: int
    community_id: Optional[int] = None
    region_id: int
    market_type: Optional[str] = None
    deal_date: Optional[date] = None
    price: Optional[float] = None
    unit_price: Optional[float] = None
    area: Optional[float] = None
    rooms: Optional[str] = None
    source: str
    source_url: Optional[str] = None

    class Config:
        from_attributes = True


class PricePoint(BaseModel):
    date: str
    avg_unit_price: Optional[float] = None
    median_unit_price: Optional[float] = None
    sample_count: Optional[int] = None
    source: Optional[str] = None
    market_type: Optional[str] = None


class WatchlistIn(BaseModel):
    community_id: int
    note: Optional[str] = None


class WatchlistOut(BaseModel):
    id: int
    community_id: int
    note: Optional[str] = None
    community_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
