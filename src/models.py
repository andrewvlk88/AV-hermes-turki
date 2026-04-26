"""Turkí Price Intelligence - Core data models."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class Store(BaseModel):
    name: str
    url: str
    search_path: str
    type: str = "dynamic"  # dynamic (JS) or static (HTML)
    note: str = ""


class ProductPrice(BaseModel):
    product_name: str
    store_name: str
    store_url: str
    regular_price: Optional[float] = None
    sale_price: Optional[float] = None
    unit: str = "בקבוק"
    volume_ml: Optional[float] = None
    currency: str = "ILS"
    is_on_sale: bool = False
    product_url: str = ""
    image_url: str = ""
    sku: str = ""
    category: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ComparisonResult(BaseModel):
    product_name: str
    turki_price: Optional[float] = None
    turki_url: str = ""
    cheapest_store: str = ""
    cheapest_price: Optional[float] = None
    cheapest_url: str = ""
    savings_vs_turki: Optional[float] = None
    savings_percent: Optional[float] = None
    all_prices: List[dict] = []
    deals_found: List[str] = []
    anomalies: List[str] = []


class SearchQuery(BaseModel):
    raw: str
    name: str = ""
    volume_ml: Optional[float] = None


class PriceReport(BaseModel):
    query: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    results: List[ComparisonResult] = []
    summary: str = ""
    stores_checked: int = 0
    stores_responded: int = 0
    deals_found: List[str] = []
    anomalies: List[str] = []
