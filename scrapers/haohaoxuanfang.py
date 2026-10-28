"""好好选房 / 好好选房Pro 尝试采集。

公开信息：
- 官网落地页 https://www.amillion.cn/ 主要为微信小程序导流，无开放房源列表 HTML。
- 公众号「好好选房Pro」（微信号 haohaoxuanfang）内容在微信内，需登录/扫码，无稳定公开 API。

本爬虫会尝试若干公开 URL；失败则 graceful skip，并在 scrape_runs 记录原因。
若要实拉公众号/小程序数据，需用户在带微信登录的浏览器中协助抓包或导出。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, REGION_CONFIG

logger = logging.getLogger(__name__)

BASE_CANDIDATES = [
    "https://www.amillion.cn",
    "https://www.haohaoxuanfang.com",
    "https://haohaoxuanfang.com",
]


class HaohaoxuanfangScraper(BaseScraper):
    source_name = "haohaoxuanfang"

    def scrape_region(self, region_code: str) -> dict:
        cfg = REGION_CONFIG[region_code]
        region = self.get_region(region_code)
        run = self.start_run(region_code, mode="live")
        city = "苏州"
        district = cfg["district"]
        found = False

        try:
            urls = []
            for base in BASE_CANDIDATES:
                urls.extend(
                    [
                        f"{base}/",
                        f"{base}/suzhou",
                        f"{base}/city/suzhou",
                        f"{base}/search?keyword={quote(city + district)}",
                        f"{base}/ershoufang/suzhou/",
                        f"{base}/xinfang/suzhou/",
                    ]
                )
            # 去重保序
            seen = set()
            urls = [u for u in urls if not (u in seen or seen.add(u))]

            for url in urls:
                logger.info("[haohaoxuanfang] try %s", url)
                resp = self.polite_get(url, timeout=15)
                if not resp:
                    continue
                text = resp.text
                # 小程序导流页特征
                if "小程序" in text and "扫描" in text and len(text) < 20000:
                    self.stats["errors"].append(f"miniprogram-landing-only: {url}")
                    logger.warning("[haohaoxuanfang] 仅为小程序落地页，无房源列表: %s", url)
                    continue
                soup = BeautifulSoup(text, "lxml")
                cards = soup.select(
                    ".house-item, .list-item, .property-item, .community-item, [class*='house'], [class*='community']"
                )
                count = 0
                for card in cards[:40]:
                    body = card.get_text(" ", strip=True)
                    if district not in body and city not in body and "苏州" not in body:
                        continue
                    a = card.select_one("a")
                    title = (a.get_text(strip=True) if a else body)[:200]
                    if len(title) < 4:
                        continue
                    href = a.get("href") if a else None
                    if href and not href.startswith("http"):
                        href = urljoin(url, href)
                    # 仅保留真实 http(s)
                    if href and not href.startswith("http"):
                        href = None
                    price_m = re.search(r"([\d.]+)\s*万", body)
                    unit_m = re.search(r"([\d.]+)\s*元", body)
                    year_m = re.search(r"(20[2-3]\d)", body)
                    community = self.upsert_community(
                        region,
                        name=title.split()[0][:40],
                        source_id=f"hhxf-c-{hash(title)}",
                        source_url=href,
                        build_year=int(year_m.group(1)) if year_m else None,
                        market_type="ershou",
                    )
                    self.upsert_listing(
                        region,
                        community,
                        {
                            "source_id": f"hhxf-l-{hash(href or title)}",
                            "title": title,
                            "price": float(price_m.group(1)) if price_m else None,
                            "unit_price": float(unit_m.group(1)) if unit_m else None,
                            "build_year": int(year_m.group(1)) if year_m else None,
                            "source_url": href,
                            "market_type": "ershou",
                        },
                    )
                    count += 1
                if count:
                    found = True
                    self.stats["pages"] += 1
                    self.db.commit()
                    break

            if not found:
                self.stats["errors"].append(
                    "no-public-list: amillion.cn is WeChat miniprogram landing; "
                    "公众号好好选房Pro needs WeChat login/browser assist"
                )
                self.finish_run(run, status="skipped")
            else:
                self.finish_run(run, status="ok")
        except Exception as e:
            logger.exception("haohaoxuanfang error")
            self.finish_run(run, status="error", error=str(e))

        return dict(self.stats)
