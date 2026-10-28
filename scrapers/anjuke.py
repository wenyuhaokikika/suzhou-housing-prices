"""安居客二手房爬虫"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, REGION_CONFIG

logger = logging.getLogger(__name__)


def _parse_float(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d.]+", text.replace(",", ""))
    return float(m.group()) if m else None


class AnjukeScraper(BaseScraper):
    source_name = "anjuke"

    def _list_url(self, cfg: dict, page: int) -> str:
        city = cfg["anjuke_city"]
        district = cfg["anjuke_district"]
        # 安居客常见路径：https://suzhou.anjuke.com/sale/wuzhong/
        if page <= 1:
            return f"https://{city}.anjuke.com/sale/{district}/"
        return f"https://{city}.anjuke.com/sale/{district}/p{page}/"

    def _parse_card(self, item, region, base_host: str) -> bool:
        try:
            a = item.select_one("a")
            if not a:
                return False
            title = a.get("title") or a.get_text(strip=True)
            href = a.get("href") or ""
            if href and not href.startswith("http"):
                href = urljoin(base_host, href)
            source_id = None
            m = re.search(r"/(\d+)", href)
            if m:
                source_id = m.group(1)

            community_el = item.select_one(".property-content-info-comm-name, .community-name, .house-title span")
            community_name = (
                community_el.get_text(strip=True) if community_el else None
            )
            if not community_name:
                parts = re.split(r"\s+|·", title)
                community_name = parts[0][:40] if parts else title[:20]

            info_els = item.select(".property-content-info-text, .details-item, span")
            info_text = " ".join(e.get_text(strip=True) for e in info_els[:8])
            rooms = None
            area = None
            floor = None
            rm = re.search(r"(\d+室\d+厅)", info_text + title)
            if rm:
                rooms = rm.group(1)
            am = re.search(r"([\d.]+)\s*m|([\d.]+)\s*平", info_text + title, re.I)
            if am:
                area = float(am.group(1) or am.group(2))
            fm = re.search(r"(\d+/\d+层|[低中高]层)", info_text)
            if fm:
                floor = fm.group(1)

            price_el = item.select_one(".property-price-total-num, .price-det, .price em, strong")
            price = _parse_float(price_el.get_text() if price_el else "")
            unit_el = item.select_one(".property-price-average, .unit-price, .unit")
            unit_price = _parse_float(unit_el.get_text() if unit_el else "")

            community = self.upsert_community(
                region,
                name=community_name,
                source_id=f"ajk-c-{community_name}",
                source_url=href,
            )
            self.upsert_listing(
                region,
                community,
                {
                    "source_id": source_id or f"ajk-l-{hash(href or title)}",
                    "title": title,
                    "price": price,
                    "unit_price": unit_price,
                    "area": area,
                    "rooms": rooms,
                    "floor": floor,
                    "source_url": href,
                    "listing_type": "sale",
                },
            )
            return True
        except Exception as e:
            logger.debug("安居客解析失败: %s", e)
            return False

    def scrape_region(self, region_code: str) -> dict:
        cfg = REGION_CONFIG[region_code]
        region = self.get_region(region_code)
        run = self.start_run(region_code, mode="live")
        base_host = f"https://{cfg['anjuke_city']}.anjuke.com"
        blocked = False

        try:
            for page in range(1, self.max_pages + 1):
                url = self._list_url(cfg, page)
                logger.info("[anjuke] %s p%s %s", region_code, page, url)
                resp = self.polite_get(url)
                if not resp:
                    blocked = True
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select(
                    ".property, .list-item, .zu-itemmod, li.list-item, .houselist-mod-new li"
                )
                if not cards:
                    cards = soup.select("[class*='property'], [class*='list-item']")
                if not cards:
                    logger.warning("[anjuke] 未找到列表卡片: %s", url)
                    blocked = True
                    self.stats["errors"].append(f"no-cards: {url}")
                    break
                self.stats["pages"] += 1
                for item in cards:
                    self._parse_card(item, region, base_host)
                self.db.commit()

            status = "partial" if blocked and self.stats["listings"] else (
                "blocked" if blocked else "ok"
            )
            self.finish_run(run, status=status)
        except Exception as e:
            logger.exception("anjuke scrape error")
            self.finish_run(run, status="error", error=str(e))
            raise

        return dict(self.stats)
