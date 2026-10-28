"""关注小区：加入 watchlist 并刷新快照

用法:
  python -m analysis.watch --list
  python -m analysis.watch --add 1 --note "关注学区"
  python -m analysis.watch --refresh
  python -m analysis.watch --refresh --community-id 1
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.models import init_db, get_session, Watchlist, Community
from analysis.trends import refresh_community_snapshot, yoy_mom_for_community


def main(argv=None):
    p = argparse.ArgumentParser(description="小区关注与快照刷新")
    p.add_argument("--list", action="store_true", help="列出关注")
    p.add_argument("--add", type=int, metavar="COMMUNITY_ID", help="加入关注")
    p.add_argument("--note", type=str, default=None)
    p.add_argument("--remove", type=int, metavar="COMMUNITY_ID")
    p.add_argument("--refresh", action="store_true", help="刷新快照")
    p.add_argument("--community-id", type=int, default=None)
    args = p.parse_args(argv)

    init_db()
    session = get_session()
    try:
        if args.add:
            c = session.get(Community, args.add)
            if not c:
                print(f"小区 id={args.add} 不存在")
                return
            existing = session.query(Watchlist).filter_by(community_id=args.add).first()
            if existing:
                if args.note:
                    existing.note = args.note
                print(f"已在关注列表: {c.name}")
            else:
                session.add(Watchlist(community_id=args.add, note=args.note))
                session.commit()
                print(f"已关注: {c.name}")
            refresh_community_snapshot(session, args.add)
            session.commit()

        if args.remove:
            w = session.query(Watchlist).filter_by(community_id=args.remove).first()
            if w:
                session.delete(w)
                session.commit()
                print("已取消关注")
            else:
                print("不在关注列表")

        if args.refresh:
            if args.community_id:
                ids = [args.community_id]
            else:
                ids = [w.community_id for w in session.query(Watchlist).all()]
            for cid in ids:
                snap = refresh_community_snapshot(session, cid)
                c = session.get(Community, cid)
                ch = yoy_mom_for_community(session, cid)
                name = c.name if c else cid
                if snap:
                    print(
                        f"刷新 {name}: 均价={snap.avg_unit_price} "
                        f"样本={snap.sample_count} YoY={ch.get('yoy_pct')}% MoM={ch.get('mom_pct')}%"
                    )
                else:
                    print(f"刷新 {name}: 无可用价格样本")
            session.commit()

        if args.list or (not args.add and not args.remove and not args.refresh):
            rows = session.query(Watchlist).all()
            if not rows:
                print("关注列表为空")
            for w in rows:
                c = session.get(Community, w.community_id)
                ch = yoy_mom_for_community(session, w.community_id)
                print(
                    f"  #{w.community_id} {c.name if c else '?'} "
                    f"note={w.note or '-'} YoY={ch.get('yoy_pct')} MoM={ch.get('mom_pct')}"
                )
    finally:
        session.close()


if __name__ == "__main__":
    main()
