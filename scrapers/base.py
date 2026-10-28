"""爬虫基类：限速、UA 轮换、幂等写入"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import requests
from sqlalchemy.orm import Session

from db.models import (
    Community,
    Listing,
    Transaction,
    Region,
    ScrapeRun,
    PriceSnapshot,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# 苏州市辖区（不含张家港/常熟/太仓/昆山等县级市）
REGION_CONFIG = {
    "gusu": {
        "city": "苏州", "district": "姑苏", "code": "gusu",
        "beike_city": "su", "beike_district": "gusu",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "gusu",
    },
    "huqiu": {
        "city": "苏州", "district": "虎丘", "code": "huqiu",
        "beike_city": "su", "beike_district": "huqiu",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "huqiu",
    },
    "wuzhong": {
        "city": "苏州", "district": "吴中", "code": "wuzhong",
        "beike_city": "su", "beike_district": "wuzhong",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "wuzhong",
    },
    "xiangcheng": {
        "city": "苏州", "district": "相城", "code": "xiangcheng",
        "beike_city": "su", "beike_district": "xiangcheng",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "xiangcheng",
    },
    "wujiang": {
        "city": "苏州", "district": "吴江", "code": "wujiang",
        "beike_city": "su", "beike_district": "wujiang",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "wujiang",
    },
    "sip": {
        "city": "苏州", "district": "工业园区", "code": "sip",
        "beike_city": "su", "beike_district": "gongyeyuanqu",
        "lianjia_city": "su", "anjuke_city": "suzhou", "anjuke_district": "yuanqu",
    },
}

# 明确排除的县级市（不入库、不爬取）
EXCLUDED_COUNTY_LEVEL = ["张家港", "常熟", "太仓", "昆山"]


class BaseScraper(ABC):
    source_name: str = "base"
    sleep_min: float = 1.0
    sleep_max: float = 2.5

    def __init__(self, session: Session, max_pages: int = 3):
        self.db = session
        self.max_pages = max_pages
        self.http = requests.Session()
        self.stats = {
            "pages": 0,
            "listings": 0,
            "txns": 0,
            "communities": 0,
            "errors": [],
        }

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }

    def polite_get(self, url: str, timeout: int = 20) -> Optional[requests.Response]:
        """带限速与重试的 GET"""
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))
        for attempt in range(3):
            try:
                resp = self.http.get(url, headers=self._headers(), timeout=timeout)
                if resp.status_code == 200:
                    # 简单反爬检测
                    text = resp.text
                    if any(
                        k in text
                        for k in ("验证码", "访问验证", "captcha", "人机验证", "security check")
                    ):
                        logger.warning("疑似反爬页面: %s", url)
                        self.stats["errors"].append(f"anti-bot: {url}")
                        return None
                    if len(text) < 500:
                        logger.warning("页面过短可能被拦截: %s", url)
                        self.stats["errors"].append(f"short-page: {url}")
                        return None
                    return resp
                logger.warning("HTTP %s for %s", resp.status_code, url)
            except requests.RequestException as e:
                logger.warning("请求失败 attempt=%s url=%s err=%s", attempt + 1, url, e)
                time.sleep(1.5 * (attempt + 1))
        self.stats["errors"].append(f"fetch-fail: {url}")
        return None

    def get_region(self, code: str) -> Region:
        region = self.db.query(Region).filter_by(code=code).first()
        if not region:
            cfg = REGION_CONFIG[code]
            region = Region(city=cfg["city"], district=cfg["district"], code=code)
            self.db.add(region)
            self.db.flush()
        return region

    def upsert_community(
        self,
        region: Region,
        name: str,
        source_id: Optional[str] = None,
        address: Optional[str] = None,
        source_url: Optional[str] = None,
        build_year: Optional[int] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        area_name: Optional[str] = None,
        market_type: Optional[str] = None,
        property_type: Optional[str] = None,
        developer: Optional[str] = None,
    ) -> Community:
        q = self.db.query(Community)
        community = None
        if source_id:
            community = q.filter_by(source=self.source_name, source_id=source_id).first()
        if not community:
            community = q.filter_by(region_id=region.id, name=name).first()
        if community:
            if address:
                community.address = address
            if source_url:
                community.source_url = source_url
            if build_year:
                community.build_year = build_year
            if lat is not None:
                community.lat = lat
            if lng is not None:
                community.lng = lng
            if area_name:
                community.area_name = area_name
            if market_type:
                community.market_type = market_type
            if property_type:
                community.property_type = property_type
            if developer is not None:
                community.developer = developer
            community.updated_at = datetime.now()
        else:
            community = Community(
                region_id=region.id,
                name=name,
                address=address,
                area_name=area_name,
                market_type=market_type or "ershou",
                property_type=property_type or "住宅",
                developer=developer,
                source=self.source_name,
                source_id=source_id or f"{self.source_name}-{name}",
                source_url=source_url,
                build_year=build_year,
                lat=lat,
                lng=lng,
            )
            self.db.add(community)
            self.stats["communities"] += 1
        self.db.flush()
        return community

    def upsert_listing(self, region: Region, community: Optional[Community], data: dict) -> Listing:
        source_id = data.get("source_id")
        listing = None
        if source_id:
            listing = (
                self.db.query(Listing)
                .filter_by(source=self.source_name, source_id=source_id)
                .first()
            )
        if listing:
            for k, v in data.items():
                if k not in ("source_id",) and v is not None and hasattr(listing, k):
                    setattr(listing, k, v)
            listing.scraped_at = datetime.now()
            if community:
                listing.community_id = community.id
        else:
            listing = Listing(
                community_id=community.id if community else None,
                region_id=region.id,
                listing_type=data.get("listing_type", "sale"),
                market_type=data.get("market_type", "ershou"),
                title=data.get("title"),
                price=data.get("price"),
                unit_price=data.get("unit_price"),
                area=data.get("area"),
                rooms=data.get("rooms"),
                floor=data.get("floor"),
                orientation=data.get("orientation"),
                build_year=data.get("build_year"),
                decoration=data.get("decoration"),
                source=self.source_name,
                source_id=source_id,
                source_url=data.get("source_url"),
                scraped_at=datetime.now(),
                raw_json=data.get("raw_json"),
            )
            self.db.add(listing)
            self.stats["listings"] += 1
        self.db.flush()
        return listing

    def upsert_transaction(
        self, region: Region, community: Optional[Community], data: dict
    ) -> Transaction:
        source_id = data.get("source_id")
        txn = None
        if source_id:
            txn = (
                self.db.query(Transaction)
                .filter_by(source=self.source_name, source_id=source_id)
                .first()
            )
        if txn:
            for k, v in data.items():
                if k not in ("source_id",) and v is not None and hasattr(txn, k):
                    setattr(txn, k, v)
            txn.scraped_at = datetime.now()
        else:
            txn = Transaction(
                community_id=community.id if community else None,
                region_id=region.id,
                market_type=data.get("market_type", "ershou"),
                deal_date=data.get("deal_date"),
                price=data.get("price"),
                unit_price=data.get("unit_price"),
                area=data.get("area"),
                rooms=data.get("rooms"),
                floor=data.get("floor"),
                source=self.source_name,
                source_id=source_id,
                source_url=data.get("source_url"),
                scraped_at=datetime.now(),
                raw_json=data.get("raw_json"),
            )
            self.db.add(txn)
            self.stats["txns"] += 1
        self.db.flush()
        return txn

    def start_run(self, region_code: str, mode: str = "live") -> ScrapeRun:
        run = ScrapeRun(
            region_code=region_code,
            source=self.source_name,
            mode=mode,
            status="running",
            started_at=datetime.now(),
        )
        self.db.add(run)
        self.db.commit()
        return run

    def finish_run(self, run: ScrapeRun, status: str = "ok", error: Optional[str] = None):
        run.status = status
        run.pages_fetched = self.stats["pages"]
        run.listings_upserted = self.stats["listings"]
        run.txns_upserted = self.stats["txns"]
        run.communities_upserted = self.stats["communities"]
        run.error_message = error or ("; ".join(self.stats["errors"][:5]) or None)
        run.finished_at = datetime.now()
        self.db.commit()

    @abstractmethod
    def scrape_region(self, region_code: str) -> dict:
        ...
