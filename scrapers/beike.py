"""贝壳/链家二手房与成交爬虫（同一生态）"""
from __future__ import annotations

import logging
import re
from datetime import datetime
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


def _parse_int(text: str) -> Optional[int]:
    f = _parse_float(text)
    return int(f) if f is not None else None


class BeikeScraper(BaseScraper):
    """贝壳找房 ershoufang + chengjiao"""

    source_name = "beike"

    def _ershoufang_url(self, cfg: dict, page: int) -> str:
        city = cfg["beike_city"]
        district = cfg["beike_district"]
        if page <= 1:
            return f"https://{city}.ke.com/ershoufang/{district}/"
        return f"https://{city}.ke.com/ershoufang/{district}/pg{page}/"

    def _chengjiao_url(self, cfg: dict, page: int) -> str:
        city = cfg["beike_city"]
        district = cfg["beike_district"]
        if page <= 1:
            return f"https://{city}.ke.com/chengjiao/{district}/"
        return f"https://{city}.ke.com/chengjiao/{district}/pg{page}/"

    def _alt_hosts(self, cfg: dict) -> list[str]:
        city = cfg["beike_city"]
        # ke.com 与 lianjia.com 同生态，互为备用
        return [f"https://{city}.ke.com", f"https://{city}.lianjia.com"]

    def _ershoufang_urls(self, cfg: dict, page: int) -> list[str]:
        district = cfg["beike_district"]
        urls = []
        for host in self._alt_hosts(cfg):
            if page <= 1:
                urls.append(f"{host}/ershoufang/{district}/")
            else:
                urls.append(f"{host}/ershoufang/{district}/pg{page}/")
        return urls

    def _chengjiao_urls(self, cfg: dict, page: int) -> list[str]:
        district = cfg["beike_district"]
        urls = []
        for host in self._alt_hosts(cfg):
            if page <= 1:
                urls.append(f"{host}/chengjiao/{district}/")
            else:
                urls.append(f"{host}/chengjiao/{district}/pg{page}/")
        return urls

    def _parse_listing_card(self, li, region, base_host: str) -> bool:
        try:
            title_a = li.select_one("a")
            if not title_a:
                return False
            title = title_a.get_text(strip=True)
            href = title_a.get("href") or ""
            if href and not href.startswith("http"):
                href = urljoin(base_host, href)
            source_id = None
            m = re.search(r"/(\d+)\.html", href)
            if m:
                source_id = m.group(1)

            # 小区名
            community_el = li.select_one(".positionInfo a, .flood a, .houseInfo a")
            community_name = community_el.get_text(strip=True) if community_el else None
            if not community_name:
                # 从标题猜：常见「小区名 户型」
                parts = re.split(r"\s+", title)
                community_name = parts[0] if parts else title[:20]

            info = li.select_one(".houseInfo, .house-info")
            info_text = info.get_text(" ", strip=True) if info else ""
            rooms = None
            area = None
            floor = None
            orientation = None
            year = None
            if info_text:
                rm = re.search(r"(\d+室\d+厅(?:\d+卫)?)", info_text)
                rooms = rm.group(1) if rm else None
                am = re.search(r"([\d.]+)\s*平", info_text)
                area = float(am.group(1)) if am else None
                fm = re.search(r"([低中高]\w*/共\d+层|\d+层)", info_text)
                floor = fm.group(1) if fm else None
                om = re.search(r"(东南|东北|西南|西北|东|南|西|北)", info_text)
                orientation = om.group(1) if om else None
                ym = re.search(r"(19|20)\d{2}", info_text)
                year = int(ym.group()) if ym else None

            price_el = li.select_one(".totalPrice, .price .total")
            price = _parse_float(price_el.get_text() if price_el else "")
            unit_el = li.select_one(".unitPrice, .price .unit")
            unit_price = _parse_float(unit_el.get_text() if unit_el else "")

            community = self.upsert_community(
                region,
                name=community_name,
                source_id=f"bk-c-{community_name}",
                source_url=href,
                build_year=year,
            )
            self.upsert_listing(
                region,
                community,
                {
                    "source_id": source_id or f"bk-l-{hash(href or title)}",
                    "title": title,
                    "price": price,
                    "unit_price": unit_price,
                    "area": area,
                    "rooms": rooms,
                    "floor": floor,
                    "orientation": orientation,
                    "build_year": year,
                    "source_url": href,
                    "listing_type": "sale",
                },
            )
            return True
        except Exception as e:
            logger.debug("解析挂牌失败: %s", e)
            return False

    def _parse_chengjiao_card(self, li, region, base_host: str) -> bool:
        try:
            title_a = li.select_one("a")
            if not title_a:
                return False
            title = title_a.get_text(strip=True)
            href = title_a.get("href") or ""
            if href and not href.startswith("http"):
                href = urljoin(base_host, href)
            source_id = None
            m = re.search(r"/(\d+)\.html", href) or re.search(r"/chengjiao/(\w+)", href)
            if m:
                source_id = m.group(1)

            parts = re.split(r"\s+", title)
            community_name = parts[0] if parts else title[:20]
            rooms = None
            rm = re.search(r"(\d+室\d+厅)", title)
            if rm:
                rooms = rm.group(1)

            info = li.select_one(".houseInfo, .dealHouseInfo, .address")
            info_text = info.get_text(" ", strip=True) if info else ""
            area = None
            am = re.search(r"([\d.]+)\s*平", info_text + " " + title)
            if am:
                area = float(am.group(1))

            date_el = li.select_one(".dealDate, .deal-date, .houseTime")
            deal_date = None
            if date_el:
                dm = re.search(r"(20\d{2}[.\-/]\d{1,2}(?:[.\-/]\d{1,2})?)", date_el.get_text())
                if dm:
                    raw = dm.group(1).replace(".", "-").replace("/", "-")
                    for fmt in ("%Y-%m-%d", "%Y-%m"):
                        try:
                            deal_date = datetime.strptime(raw, fmt).date()
                            break
                        except ValueError:
                            continue

            price_el = li.select_one(".totalPrice, .dealPrice, .price")
            price = _parse_float(price_el.get_text() if price_el else "")
            unit_el = li.select_one(".unitPrice, .dealUnitPrice")
            unit_price = _parse_float(unit_el.get_text() if unit_el else "")

            community = self.upsert_community(
                region,
                name=community_name,
                source_id=f"bk-c-{community_name}",
            )
            self.upsert_transaction(
                region,
                community,
                {
                    "source_id": source_id or f"bk-t-{hash(href or title)}",
                    "deal_date": deal_date,
                    "price": price,
                    "unit_price": unit_price,
                    "area": area,
                    "rooms": rooms,
                    "source_url": href,
                },
            )
            return True
        except Exception as e:
            logger.debug("解析成交失败: %s", e)
            return False

    def scrape_region(self, region_code: str) -> dict:
        cfg = REGION_CONFIG[region_code]
        region = self.get_region(region_code)
        run = self.start_run(region_code, mode="live")
        base_host = f"https://{cfg['beike_city']}.ke.com"
        blocked = False

        try:
            # 二手房列表（ke.com / lianjia.com 轮询）
            for page in range(1, self.max_pages + 1):
                got = False
                for url in self._ershoufang_urls(cfg, page):
                    logger.info("[beike] 二手房 %s p%s %s", region_code, page, url)
                    resp = self.polite_get(url)
                    if not resp:
                        continue
                    soup = BeautifulSoup(resp.text, "lxml")
                    cards = soup.select("ul.sellListContent li.clear, .sellListContent li, li.list-item")
                    if not cards:
                        cards = soup.select("[data-housecode], .LOGCLICKDATA")
                    if not cards:
                        logger.warning("[beike] 未找到挂牌卡片: %s", url)
                        self.stats["errors"].append(f"no-listing-cards: {url}")
                        continue
                    host = url.split("/ershoufang")[0]
                    self.stats["pages"] += 1
                    for li in cards:
                        self._parse_listing_card(li, region, host)
                    self.db.commit()
                    got = True
                    break
                if not got:
                    blocked = True
                    break

            # 成交列表
            if not blocked:
                for page in range(1, max(1, self.max_pages // 2) + 1):
                    got = False
                    for url in self._chengjiao_urls(cfg, page):
                        logger.info("[beike] 成交 %s p%s %s", region_code, page, url)
                        resp = self.polite_get(url)
                        if not resp:
                            continue
                        soup = BeautifulSoup(resp.text, "lxml")
                        cards = soup.select(
                            "ul.listContent li, .listContent li, li.list-item"
                        )
                        if not cards:
                            logger.warning("[beike] 未找到成交卡片: %s", url)
                            self.stats["errors"].append(f"no-chengjiao-cards: {url}")
                            continue
                        host = url.split("/chengjiao")[0]
                        self.stats["pages"] += 1
                        for li in cards:
                            self._parse_chengjiao_card(li, region, host)
                        self.db.commit()
                        got = True
                        break
                    if not got:
                        blocked = True
                        break

            status = "partial" if blocked and (self.stats["listings"] or self.stats["txns"]) else (
                "blocked" if blocked else "ok"
            )
            self.finish_run(run, status=status)
        except Exception as e:
            logger.exception("beike scrape error")
            self.finish_run(run, status="error", error=str(e))
            raise

        return dict(self.stats)
