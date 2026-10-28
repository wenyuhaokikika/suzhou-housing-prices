"""苏州六区演示数据：真实小区名 + 新房/二手；加大挂牌与成交量；source=demo"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import date

from scrapers.base import BaseScraper, REGION_CONFIG
from scrapers.suzhou_communities import COMMUNITIES_BY_REGION
from db.models import PriceSnapshot

logger = logging.getLogger(__name__)

# 目录价偏「挂牌口径」；成交基线按区下调到更接近近年苏州公开成交水平（仍为示意）
DEAL_SCALE = {
    "gusu": 0.58,
    "huqiu": 0.70,
    "wuzhong": 0.68,
    "xiangcheng": 0.68,
    "wujiang": 0.72,
    "sip": 0.70,
}
# 挂牌相对成交溢价（苏州二手挂牌常高于成交）
LISTING_PREMIUM = (1.10, 1.18)

ROOM_TYPES = ["2室1厅", "2室2厅", "3室2厅", "3室1厅", "4室2厅", "3室2厅1卫", "1室1厅"]
FLOORS = ["低楼层/共18层", "中楼层/共11层", "高楼层/共25层", "中楼层/共6层", "低楼层/共33层", "高楼层/共28层"]
ORIENT = ["南", "南北", "东南", "东", "西南", "北"]


def _sid(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class DemoScraper(BaseScraper):
    source_name = "demo"
    sleep_min = 0
    sleep_max = 0

    def scrape_region(self, region_code: str) -> dict:
        if region_code not in COMMUNITIES_BY_REGION:
            raise ValueError(f"不支持的区域（仅苏州六区）: {region_code}")
        region = self.get_region(region_code)
        run = self.start_run(region_code, mode="demo")
        rng = random.Random(1000 + sum(ord(c) for c in region_code))

        try:
            today = date.today()
            start = date(today.year - 3, today.month, 1)
            for meta in COMMUNITIES_BY_REGION[region_code]:
                market = meta["market"]
                community = self.upsert_community(
                    region,
                    name=meta["name"],
                    source_id=f"demo-c-{region_code}-{market}-{meta['name']}",
                    address=meta["address"],
                    build_year=meta["year"],
                    source_url=None,  # demo 不提供可点击假链接
                    area_name=meta["area"],
                    market_type=market,
                    property_type=meta["prop"],
                    developer=meta.get("dev"),
                )

                months = []
                d = start
                while d <= today:
                    months.append(d)
                    d = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)

                n = len(months)
                # 成交基线（主指标）；挂牌在成交之上
                scale = DEAL_SCALE.get(region_code, 0.70)
                deal_base = meta["price"] * scale
                # 超高价别墅/豪宅再压一点，避免极端偏离
                if deal_base > 55000:
                    deal_base = meta["price"] * min(scale, 0.55)
                vol = meta["vol"]
                for i, mdate in enumerate(months):
                    if market == "ershou":
                        trend = 1.0 - 0.08 * (i / max(n - 1, 1)) + 0.02 * (i / max(n - 1, 1)) ** 2
                    else:
                        trend = 1.0 - 0.03 * (i / max(n - 1, 1)) + 0.01 * rng.uniform(-1, 1)
                    noise = 1.0 + rng.uniform(-vol, vol) * 0.25
                    # 快照 = 当月成交均价
                    avg_up = round(deal_base * trend * noise, 0)
                    median_up = round(avg_up * rng.uniform(0.97, 1.03), 0)
                    sample = rng.randint(4, 22) if market == "ershou" else rng.randint(2, 12)

                    existing = (
                        self.db.query(PriceSnapshot)
                        .filter_by(
                            community_id=community.id,
                            snap_date=mdate,
                            source="demo",
                            market_type=market,
                        )
                        .first()
                    )
                    if existing:
                        existing.avg_unit_price = avg_up
                        existing.median_unit_price = median_up
                        existing.min_unit_price = round(avg_up * 0.9, 0)
                        existing.max_unit_price = round(avg_up * 1.12, 0)
                        existing.sample_count = sample
                    else:
                        self.db.add(
                            PriceSnapshot(
                                community_id=community.id,
                                snap_date=mdate,
                                market_type=market,
                                avg_unit_price=avg_up,
                                median_unit_price=median_up,
                                min_unit_price=round(avg_up * 0.9, 0),
                                max_unit_price=round(avg_up * 1.12, 0),
                                sample_count=sample,
                                source="demo",
                            )
                        )

                    txn_n = rng.randint(2, 5) if market == "ershou" else rng.randint(1, 3)
                    for j in range(txn_n):
                        day = min(28, 1 + j * 5 + rng.randint(0, 2))
                        deal = date(mdate.year, mdate.month, day)
                        area = round(
                            rng.uniform(70, 150) if market == "ershou" else rng.uniform(89, 165),
                            1,
                        )
                        up = round(avg_up * rng.uniform(0.95, 1.05), 0)
                        self.upsert_transaction(
                            region,
                            community,
                            {
                                "source_id": _sid("t", region_code, market, meta["name"], deal, j),
                                "deal_date": deal,
                                "price": round(up * area / 10000, 1),
                                "unit_price": up,
                                "area": area,
                                "rooms": rng.choice(ROOM_TYPES),
                                "floor": rng.choice(FLOORS),
                                "market_type": market,
                                "source_url": None,
                            },
                        )

                # 挂牌：明显高于成交（溢价），仅作参考
                listing_n = rng.randint(8, 16) if market == "ershou" else rng.randint(5, 10)
                prem_lo, prem_hi = LISTING_PREMIUM
                for k in range(listing_n):
                    area = round(
                        rng.uniform(70, 145) if market == "ershou" else rng.uniform(89, 165),
                        1,
                    )
                    up = round(deal_base * rng.uniform(prem_lo, prem_hi), 0)
                    rooms = rng.choice(ROOM_TYPES)
                    prefix = "在售挂牌" if market == "ershou" else "新房报价"
                    self.upsert_listing(
                        region,
                        community,
                        {
                            "source_id": _sid("l", region_code, market, meta["name"], k),
                            "title": f"{prefix}·{meta['name']} {rooms} {area}㎡",
                            "price": round(up * area / 10000, 1),
                            "unit_price": up,
                            "area": area,
                            "rooms": rooms,
                            "floor": rng.choice(FLOORS),
                            "orientation": rng.choice(ORIENT),
                            "build_year": meta["year"],
                            "decoration": rng.choice(["精装", "简装", "毛坯"])
                            if market == "ershou"
                            else rng.choice(["精装交付", "毛坯", "装修交付"]),
                            "market_type": market,
                            "source_url": None,
                            "listing_type": "sale",
                        },
                    )

                self.stats["pages"] += 1
                self.db.commit()

            self.finish_run(run, status="ok")
            logger.info(
                "[demo] %s done +communities=%s +listings=%s +txns=%s",
                region_code,
                self.stats["communities"],
                self.stats["listings"],
                self.stats["txns"],
            )
        except Exception as e:
            logger.exception("demo seed error")
            self.finish_run(run, status="error", error=str(e))
            raise
        return dict(self.stats)
