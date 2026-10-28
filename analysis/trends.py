"""价格趋势与区域对比：以成交价为主，挂牌价为辅"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import (
    Community,
    Listing,
    Transaction,
    PriceSnapshot,
    Region,
    Watchlist,
)

MARKET_LABEL = {"ershou": "二手房", "xinfang": "新房"}


def _avg_deal(session: Session, region_id: int, market_type: Optional[str] = None) -> Optional[float]:
    q = session.query(func.avg(Transaction.unit_price)).filter(
        Transaction.region_id == region_id,
        Transaction.unit_price.isnot(None),
    )
    if market_type:
        q = q.filter(Transaction.market_type == market_type)
    avg = q.scalar()
    return round(float(avg), 1) if avg else None


def _avg_listing(session: Session, region_id: int, market_type: Optional[str] = None) -> Optional[float]:
    q = session.query(func.avg(Listing.unit_price)).filter(
        Listing.region_id == region_id,
        Listing.unit_price.isnot(None),
    )
    if market_type:
        q = q.filter(Listing.market_type == market_type)
    avg = q.scalar()
    return round(float(avg), 1) if avg else None


def discount_pct(listing: Optional[float], deal: Optional[float]) -> Optional[float]:
    """挂牌相对成交的溢价%（正数=挂牌更高）"""
    if not listing or not deal or deal == 0:
        return None
    return round((listing - deal) / deal * 100, 1)


def community_deal_series(
    session: Session, community_id: int, market_type: Optional[str] = None
) -> list[dict]:
    """月度成交均价序列（主图用）"""
    # 优先用快照（demo 已按成交写入）
    q = session.query(PriceSnapshot).filter_by(community_id=community_id)
    if market_type:
        q = q.filter_by(market_type=market_type)
    snaps = q.order_by(PriceSnapshot.snap_date).all()
    if snaps:
        return [
            {
                "date": s.snap_date.isoformat(),
                "avg_unit_price": s.avg_unit_price,
                "median_unit_price": s.median_unit_price,
                "sample_count": s.sample_count,
                "source": s.source,
                "market_type": s.market_type,
                "metric": "deal",
            }
            for s in snaps
        ]
    # 按月聚合成交
    rows = (
        session.query(
            Transaction.deal_date,
            Transaction.unit_price,
        )
        .filter(
            Transaction.community_id == community_id,
            Transaction.unit_price.isnot(None),
            Transaction.deal_date.isnot(None),
        )
        .all()
    )
    if market_type:
        rows = [
            (d, u)
            for d, u in session.query(Transaction.deal_date, Transaction.unit_price)
            .filter(
                Transaction.community_id == community_id,
                Transaction.unit_price.isnot(None),
                Transaction.deal_date.isnot(None),
                Transaction.market_type == market_type,
            )
            .all()
        ]
    by_month: dict[str, list[float]] = {}
    for d, u in rows:
        key = f"{d.year:04d}-{d.month:02d}-01"
        by_month.setdefault(key, []).append(float(u))
    out = []
    for key in sorted(by_month):
        vals = by_month[key]
        out.append(
            {
                "date": key,
                "avg_unit_price": round(sum(vals) / len(vals), 1),
                "median_unit_price": round(sorted(vals)[len(vals) // 2], 1),
                "sample_count": len(vals),
                "source": "txn-month",
                "market_type": market_type or "ershou",
                "metric": "deal",
            }
        )
    return out


def community_price_series(
    session: Session, community_id: int, market_type: Optional[str] = None
) -> list[dict]:
    """兼容旧名：返回成交序列"""
    return community_deal_series(session, community_id, market_type)


def refresh_community_snapshot(session: Session, community_id: int) -> Optional[PriceSnapshot]:
    """按近期成交刷新快照（成交优先）"""
    today = date.today()
    c = session.get(Community, community_id)
    market = (c.market_type if c else None) or "ershou"
    prices = [
        r[0]
        for r in session.query(Transaction.unit_price)
        .filter(
            Transaction.community_id == community_id,
            Transaction.unit_price.isnot(None),
            Transaction.market_type == market,
        )
        .order_by(Transaction.deal_date.desc())
        .limit(30)
        .all()
    ]
    if not prices:
        prices = [
            r[0]
            for r in session.query(Listing.unit_price)
            .filter(
                Listing.community_id == community_id,
                Listing.unit_price.isnot(None),
                Listing.market_type == market,
            )
            .all()
        ]
    if not prices:
        return None
    prices = sorted(prices)
    n = len(prices)
    avg = sum(prices) / n
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    snap = (
        session.query(PriceSnapshot)
        .filter_by(
            community_id=community_id, snap_date=today, source="computed", market_type=market
        )
        .first()
    )
    if not snap:
        snap = PriceSnapshot(
            community_id=community_id, snap_date=today, source="computed", market_type=market
        )
        session.add(snap)
    snap.avg_unit_price = round(avg, 1)
    snap.median_unit_price = round(median, 1)
    snap.min_unit_price = round(min(prices), 1)
    snap.max_unit_price = round(max(prices), 1)
    snap.sample_count = n
    session.flush()
    return snap


def compare_regions(session: Session) -> dict[str, Any]:
    regions = session.query(Region).order_by(Region.id).all()
    result = {"regions": [], "city": "苏州", "excluded": ["张家港", "常熟", "太仓", "昆山"]}
    for r in regions:
        deal_e = _avg_deal(session, r.id, "ershou")
        deal_x = _avg_deal(session, r.id, "xinfang")
        list_e = _avg_listing(session, r.id, "ershou")
        list_x = _avg_listing(session, r.id, "xinfang")
        listing_cnt = session.query(func.count(Listing.id)).filter_by(region_id=r.id).scalar()
        txn_cnt = session.query(func.count(Transaction.id)).filter_by(region_id=r.id).scalar()
        community_cnt = session.query(func.count(Community.id)).filter_by(region_id=r.id).scalar()
        result["regions"].append(
            {
                "code": r.code,
                "city": r.city,
                "district": r.district,
                # 主指标：成交
                "avg_ershou": deal_e,
                "avg_xinfang": deal_x,
                "avg_deal_ershou": deal_e,
                "avg_deal_xinfang": deal_x,
                "avg_listing_ershou": list_e,
                "avg_listing_xinfang": list_x,
                "premium_ershou_pct": discount_pct(list_e, deal_e),
                "premium_xinfang_pct": discount_pct(list_x, deal_x),
                "avg_unit_price": deal_e or deal_x,
                "listings": listing_cnt,
                "transactions": txn_cnt,
                "communities": community_cnt,
                "ershou_communities": session.query(func.count(Community.id))
                .filter_by(region_id=r.id, market_type="ershou")
                .scalar(),
                "xinfang_communities": session.query(func.count(Community.id))
                .filter_by(region_id=r.id, market_type="xinfang")
                .scalar(),
            }
        )
    with_e = [x for x in result["regions"] if x.get("avg_deal_ershou")]
    with_x = [x for x in result["regions"] if x.get("avg_deal_xinfang")]
    parts = [
        f"覆盖苏州 {len(result['regions'])} 个市辖区（已排除张家港/常熟/太仓/昆山）。",
        "以下均价均以<strong>成交单价</strong>为准（挂牌仅作参考）。",
    ]
    if with_e:
        hi = max(with_e, key=lambda x: x["avg_deal_ershou"])
        lo = min(with_e, key=lambda x: x["avg_deal_ershou"])
        parts.append(
            f"二手成交均价最高 {hi['district']}约 {hi['avg_deal_ershou']:.0f} 元/㎡，"
            f"最低 {lo['district']}约 {lo['avg_deal_ershou']:.0f} 元/㎡"
        )
    if with_x:
        hi = max(with_x, key=lambda x: x["avg_deal_xinfang"])
        lo = min(with_x, key=lambda x: x["avg_deal_xinfang"])
        parts.append(
            f"新房成交/备案均价最高 {hi['district']}约 {hi['avg_deal_xinfang']:.0f} 元/㎡，"
            f"最低 {lo['district']}约 {lo['avg_deal_xinfang']:.0f} 元/㎡"
        )
    result["summary_zh"] = "；".join(parts) + "。"
    result["diff_pct_ershou"] = None
    result["diff_pct_xinfang"] = None
    return result


def yoy_mom_for_community(session: Session, community_id: int) -> dict[str, Any]:
    snaps = (
        session.query(PriceSnapshot)
        .filter_by(community_id=community_id)
        .order_by(PriceSnapshot.snap_date.desc())
        .all()
    )
    if len(snaps) < 2:
        return {"yoy_pct": None, "mom_pct": None, "latest": None}
    latest = snaps[0]
    mom = yoy = None
    if snaps[1].avg_unit_price and latest.avg_unit_price:
        mom = round(
            (latest.avg_unit_price - snaps[1].avg_unit_price) / snaps[1].avg_unit_price * 100, 2
        )
    for s in snaps:
        if (latest.snap_date - s.snap_date).days >= 360 and s.avg_unit_price and latest.avg_unit_price:
            yoy = round(
                (latest.avg_unit_price - s.avg_unit_price) / s.avg_unit_price * 100, 2
            )
            break
    return {
        "latest": {"date": latest.snap_date.isoformat(), "avg_unit_price": latest.avg_unit_price},
        "mom_pct": mom,
        "yoy_pct": yoy,
    }


def latest_community_deal_price(session: Session, community_id: int) -> Optional[float]:
    """小区最新参考成交均价"""
    snap = (
        session.query(PriceSnapshot)
        .filter_by(community_id=community_id)
        .order_by(PriceSnapshot.snap_date.desc())
        .first()
    )
    if snap and snap.avg_unit_price:
        return snap.avg_unit_price
    avg = (
        session.query(func.avg(Transaction.unit_price))
        .filter(
            Transaction.community_id == community_id,
            Transaction.unit_price.isnot(None),
        )
        .scalar()
    )
    return round(float(avg), 1) if avg else None


def latest_community_listing_price(session: Session, community_id: int) -> Optional[float]:
    avg = (
        session.query(func.avg(Listing.unit_price))
        .filter(Listing.community_id == community_id, Listing.unit_price.isnot(None))
        .scalar()
    )
    return round(float(avg), 1) if avg else None


def latest_community_price(session: Session, community_id: int) -> Optional[float]:
    """兼容旧接口：返回成交均价"""
    return latest_community_deal_price(session, community_id)


def community_detail_stats(session: Session, community_id: int) -> dict[str, Any]:
    listings = session.query(Listing).filter_by(community_id=community_id).all()
    txns = (
        session.query(Transaction)
        .filter_by(community_id=community_id)
        .order_by(Transaction.deal_date.desc())
        .all()
    )
    deal_ups = [t.unit_price for t in txns if t.unit_price]
    list_ups = [l.unit_price for l in listings if l.unit_price]
    deal_areas = [t.area for t in txns if t.area]
    rooms = Counter(t.rooms for t in txns if t.rooms)
    if not rooms:
        rooms = Counter(l.rooms for l in listings if l.rooms)
    deal_avg = round(sum(deal_ups) / len(deal_ups), 1) if deal_ups else None
    list_avg = round(sum(list_ups) / len(list_ups), 1) if list_ups else None
    return {
        "listing_count": len(listings),
        "txn_count": len(txns),
        "rooms_dist": [{"rooms": k, "count": v} for k, v in rooms.most_common()],
        "area_min": min(deal_areas) if deal_areas else None,
        "area_max": max(deal_areas) if deal_areas else None,
        "area_avg": round(sum(deal_areas) / len(deal_areas), 1) if deal_areas else None,
        # 主：成交
        "deal_unit_price_avg": deal_avg,
        "deal_unit_price_min": min(deal_ups) if deal_ups else None,
        "deal_unit_price_max": max(deal_ups) if deal_ups else None,
        # 辅：挂牌
        "listing_unit_price_avg": list_avg,
        "listing_unit_price_min": min(list_ups) if list_ups else None,
        "listing_unit_price_max": max(list_ups) if list_ups else None,
        "listing_premium_pct": discount_pct(list_avg, deal_avg),
        # 兼容旧字段 → 指向成交
        "unit_price_avg": deal_avg,
        "unit_price_min": min(deal_ups) if deal_ups else None,
        "unit_price_max": max(deal_ups) if deal_ups else None,
        "changes": yoy_mom_for_community(session, community_id),
    }


def top_communities(session: Session, region_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    q = session.query(Community)
    if region_id:
        q = q.filter_by(region_id=region_id)
    rows = []
    for c in q.all():
        deal = latest_community_deal_price(session, c.id)
        listing = latest_community_listing_price(session, c.id)
        if deal is None:
            continue
        r = session.get(Region, c.region_id)
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "area_name": c.area_name,
                "market_type": c.market_type,
                "market_label": MARKET_LABEL.get(c.market_type, c.market_type),
                "build_year": c.build_year,
                "property_type": c.property_type,
                "avg_unit_price": deal,
                "avg_deal_price": deal,
                "avg_listing_price": listing,
                "listing_premium_pct": discount_pct(listing, deal),
                "region_code": r.code if r else None,
                "district": r.district if r else None,
            }
        )
    rows.sort(key=lambda x: x["avg_deal_price"] or 0, reverse=True)
    return rows[:limit]


def overview_stats(session: Session) -> dict[str, Any]:
    return {
        "regions": session.query(func.count(Region.id)).scalar(),
        "communities": session.query(func.count(Community.id)).scalar(),
        "listings": session.query(func.count(Listing.id)).scalar(),
        "transactions": session.query(func.count(Transaction.id)).scalar(),
        "snapshots": session.query(func.count(PriceSnapshot.id)).scalar(),
        "watchlist": session.query(func.count(Watchlist.id)).scalar(),
        "ershou_listings": session.query(func.count(Listing.id))
        .filter_by(market_type="ershou")
        .scalar(),
        "xinfang_listings": session.query(func.count(Listing.id))
        .filter_by(market_type="xinfang")
        .scalar(),
        "compare": compare_regions(session),
        "tops": top_communities(session, limit=20),
    }


def build_report(session: Session) -> dict[str, Any]:
    ov = overview_stats(session)
    compare = ov["compare"]
    tops = []
    for r in session.query(Region).all():
        tops.append(
            {
                "region": r.code,
                "district": r.district,
                "top_communities": top_communities(session, region_id=r.id, limit=5),
            }
        )
    return {
        "generated_at": date.today().isoformat(),
        "overview": {
            "communities": ov["communities"],
            "listings": ov["listings"],
            "transactions": ov["transactions"],
            "snapshots": ov["snapshots"],
            "ershou_listings": ov["ershou_listings"],
            "xinfang_listings": ov["xinfang_listings"],
        },
        "compare": compare,
        "tops": tops,
        "summary_zh": compare.get("summary_zh", ""),
    }
