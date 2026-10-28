"""生成中文分析报告并写入 data/report.json

用法: python -m analysis.report
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.models import init_db, get_session
from analysis.trends import build_report


def main():
    init_db()
    session = get_session()
    try:
        report = build_report(session)
    finally:
        session.close()

    out = os.path.join(ROOT, "data", "report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("======== 房价分析摘要 ========")
    print(report.get("summary_zh", ""))
    print()
    print("对比:")
    for r in report.get("compare", {}).get("regions", []):
        print(
            f"  {r['city']}{r['district']}: 均价={r['avg_unit_price']} "
            f"小区={r['communities']} 挂牌={r['listings']} 成交={r['transactions']}"
        )
    print(f"\n完整报告已写入: {out}")
    return report


if __name__ == "__main__":
    main()
