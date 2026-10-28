"""爬虫入口 CLI

用法:
  python -m scrapers.run --region all --source all --demo
  python -m scrapers.run --region wuzhong --source beike --max-pages 3
  python -m scrapers.run --region fengxian --source anjuke --max-pages 2
"""
from __future__ import annotations

import argparse
import logging
import sys
import os

# 保证项目根在 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.models import init_db, get_session
from scrapers.beike import BeikeScraper
from scrapers.anjuke import AnjukeScraper
from scrapers.demo import DemoScraper
from scrapers.haohaoxuanfang import HaohaoxuanfangScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scrapers.run")

SCRAPERS = {
    "beike": BeikeScraper,
    "lianjia": BeikeScraper,  # 同生态
    "anjuke": AnjukeScraper,
    "haohaoxuanfang": HaohaoxuanfangScraper,
    "demo": DemoScraper,
}

REGIONS = ["gusu", "huqiu", "wuzhong", "xiangcheng", "wujiang", "sip"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="苏州市辖区房价数据采集（不含张家港/常熟/太仓/昆山）")
    p.add_argument(
        "--region",
        choices=["gusu", "huqiu", "wuzhong", "xiangcheng", "wujiang", "sip", "all"],
        default="all",
        help="区域",
    )
    p.add_argument(
        "--source",
        choices=["beike", "lianjia", "anjuke", "haohaoxuanfang", "demo", "all"],
        default="all",
        help="数据源",
    )
    p.add_argument("--max-pages", type=int, default=3, help="每个列表最大页数（直播演示宜小）")
    p.add_argument(
        "--demo",
        action="store_true",
        help="写入演示合成数据（近三年趋势），保证端到端可用",
    )
    p.add_argument(
        "--demo-only",
        action="store_true",
        help="仅跑 demo，不尝试真实站点",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    init_db()
    session = get_session()

    regions = REGIONS if args.region == "all" else [args.region]

    # 源列表
    if args.demo_only:
        sources = ["demo"]
    elif args.demo or args.source == "demo":
        # demo 优先填充，再尝试 live
        if args.source == "demo":
            sources = ["demo"]
        elif args.source == "all":
            sources = ["demo", "beike", "anjuke", "haohaoxuanfang"]
        else:
            sources = ["demo", args.source]
    elif args.source == "all":
        sources = ["beike", "anjuke", "haohaoxuanfang"]
    else:
        sources = [args.source]

    summary = []
    try:
        for region in regions:
            for src in sources:
                cls = SCRAPERS[src]
                logger.info("==== 开始 %s / %s (max_pages=%s) ====", region, src, args.max_pages)
                scraper = cls(session, max_pages=args.max_pages)
                try:
                    stats = scraper.scrape_region(region)
                    summary.append({"region": region, "source": src, "stats": stats, "ok": True})
                    logger.info("完成 %s/%s -> %s", region, src, stats)
                except Exception as e:
                    logger.exception("失败 %s/%s: %s", region, src, e)
                    summary.append(
                        {"region": region, "source": src, "error": str(e), "ok": False}
                    )
                session.commit()
    finally:
        session.close()

    print("\n======== 爬取汇总 ========")
    for row in summary:
        if row["ok"]:
            s = row["stats"]
            print(
                f"  [{row['source']:16}] {row['region']:10} "
                f"pages={s.get('pages', 0)} listings+={s.get('listings', 0)} "
                f"txns+={s.get('txns', 0)} communities+={s.get('communities', 0)} "
                f"errors={len(s.get('errors') or [])}"
            )
        else:
            print(f"  [{row['source']:16}] {row['region']:10} ERROR: {row.get('error')}")
    print("数据库: data/housing.db")
    return summary


if __name__ == "__main__":
    main()
