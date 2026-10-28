"""FastAPI：多页房价看板 + JSON API

启动: uvicorn app.main:app --host 0.0.0.0 --port 8765
"""
from __future__ import annotations

import os
import sys
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.models import (
    init_db,
    get_session,
    Region,
    Community,
    Listing,
    Transaction,
    Watchlist,
    ScrapeRun,
)
from app.schemas import (
    RegionOut,
    CommunityOut,
    ListingOut,
    TransactionOut,
    PricePoint,
    WatchlistIn,
    WatchlistOut,
)
from analysis.trends import (
    community_price_series,
    compare_regions,
    overview_stats,
    refresh_community_snapshot,
    yoy_mom_for_community,
    community_detail_stats,
    top_communities,
    latest_community_price,
    latest_community_deal_price,
    latest_community_listing_price,
    discount_pct,
    MARKET_LABEL,
)

app = FastAPI(
    title="苏州各区房价数据 API",
    description="苏州市辖区（姑苏/虎丘/吴中/相城/吴江/工业园区）· 不含县级市 · 新房与二手拆分",
    version="2.0.0",
)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
_static = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static), name="static")


def get_db():
    init_db()
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- HTML 多页 ----------


@app.get("/about-data", response_class=HTMLResponse)
def page_about_data(request: Request):
    return templates.TemplateResponse(request, "about_data.html", {"nav": "about"})

@app.get("/", response_class=HTMLResponse)
def page_home(request: Request, db: Session = Depends(get_db)):
    ov = overview_stats(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"nav": "home", "overview": ov, "compare": ov["compare"], "tops": ov["tops"]},
    )


@app.get("/regions/{code}", response_class=HTMLResponse)
def page_region(
    code: str,
    request: Request,
    market: Optional[str] = None,
    q: Optional[str] = None,
    area: Optional[str] = None,
    property: Optional[str] = Query(None, alias="property"),
    developer: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    db: Session = Depends(get_db),
):
    region = db.query(Region).filter_by(code=code).first()
    if not region:
        raise HTTPException(404, "未知区域")
    query = db.query(Community).filter_by(region_id=region.id)
    if market in ("ershou", "xinfang"):
        query = query.filter_by(market_type=market)
    if q:
        query = query.filter(Community.name.contains(q))
    if area:
        query = query.filter(Community.area_name.contains(area))
    if property:
        query = query.filter(Community.property_type.contains(property))
    if developer:
        query = query.filter(Community.developer.contains(developer))
    if year_min is not None:
        query = query.filter(Community.build_year >= year_min)
    if year_max is not None:
        query = query.filter(Community.build_year <= year_max)
    communities = query.order_by(Community.market_type, Community.name).all()
    rows = []
    for c in communities:
        deal = latest_community_deal_price(db, c.id)
        listing_p = latest_community_listing_price(db, c.id)
        if price_min is not None and (deal is None or deal < price_min):
            continue
        if price_max is not None and (deal is None or deal > price_max):
            continue
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "area_name": c.area_name,
                "market_type": c.market_type,
                "market_label": MARKET_LABEL.get(c.market_type, c.market_type),
                "property_type": c.property_type,
                "build_year": c.build_year,
                "developer": c.developer,
                "avg_unit_price": deal,
                "avg_deal_price": deal,
                "avg_listing_price": listing_p,
                "listing_premium_pct": discount_pct(listing_p, deal),
                "listing_count": db.query(func.count(Listing.id))
                .filter_by(community_id=c.id)
                .scalar(),
                "txn_count": db.query(func.count(Transaction.id))
                .filter_by(community_id=c.id)
                .scalar(),
            }
        )
    rows.sort(key=lambda x: (x["market_type"], -(x["avg_deal_price"] or 0)))
    compare = compare_regions(db)
    stats = next((r for r in compare["regions"] if r["code"] == code), {})
    return templates.TemplateResponse(
        request,
        "region.html",
        {
            "nav": code,
            "region": region,
            "communities": communities,
            "community_rows": rows,
            "market_filter": market,
            "stats": stats,
            "filters": {
                "q": q,
                "area": area,
                "market": market,
                "property": property,
                "developer": developer,
                "year_min": year_min,
                "year_max": year_max,
                "price_min": price_min,
                "price_max": price_max,
            },
        },
    )


@app.get("/communities", response_class=HTMLResponse)
def page_communities(
    request: Request,
    region: Optional[str] = None,
    market: Optional[str] = None,
    q: Optional[str] = None,
    area: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Community)
    if region:
        reg = db.query(Region).filter_by(code=region).first()
        if reg:
            query = query.filter(Community.region_id == reg.id)
    if market in ("ershou", "xinfang"):
        query = query.filter(Community.market_type == market)
    if q:
        query = query.filter(Community.name.contains(q))
    if area:
        query = query.filter(Community.area_name.contains(area))
    if year_min is not None:
        query = query.filter(Community.build_year >= year_min)
    if year_max is not None:
        query = query.filter(Community.build_year <= year_max)
    rows = []
    for c in query.order_by(Community.name).all():
        deal = latest_community_deal_price(db, c.id)
        if price_min is not None and (deal is None or deal < price_min):
            continue
        if price_max is not None and (deal is None or deal > price_max):
            continue
        r = db.get(Region, c.region_id)
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "area_name": c.area_name,
                "market_type": c.market_type,
                "market_label": MARKET_LABEL.get(c.market_type, c.market_type),
                "build_year": c.build_year,
                "avg_unit_price": deal,
                "avg_deal_price": deal,
                "city": r.city if r else "",
                "district": r.district if r else "",
            }
        )
    return templates.TemplateResponse(
        request,
        "communities.html",
        {
            "nav": "communities",
            "rows": rows,
            "region": region,
            "market": market,
            "q": q,
            "area": area,
            "year_min": year_min,
            "year_max": year_max,
            "price_min": price_min,
            "price_max": price_max,
        },
    )


@app.get("/communities/{community_id}", response_class=HTMLResponse)
def page_community_detail(
    community_id: int,
    request: Request,
    rooms: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    unit_min: Optional[float] = None,
    unit_max: Optional[float] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    db: Session = Depends(get_db),
):
    c = db.get(Community, community_id)
    if not c:
        raise HTTPException(404, "小区不存在")
    region = db.get(Region, c.region_id)
    stats = community_detail_stats(db, community_id)
    series = community_price_series(db, community_id, market_type=c.market_type)
    lq = db.query(Listing).filter_by(community_id=community_id)
    if rooms:
        lq = lq.filter(Listing.rooms.contains(rooms))
    if price_min is not None:
        lq = lq.filter(Listing.price >= price_min)
    if price_max is not None:
        lq = lq.filter(Listing.price <= price_max)
    if unit_min is not None:
        lq = lq.filter(Listing.unit_price >= unit_min)
    if unit_max is not None:
        lq = lq.filter(Listing.unit_price <= unit_max)
    if area_min is not None:
        lq = lq.filter(Listing.area >= area_min)
    if area_max is not None:
        lq = lq.filter(Listing.area <= area_max)
    listings = lq.order_by(Listing.unit_price.desc()).limit(80).all()
    txns = (
        db.query(Transaction)
        .filter_by(community_id=community_id)
        .order_by(Transaction.deal_date.desc())
        .limit(80)
        .all()
    )
    watched = db.query(Watchlist).filter_by(community_id=community_id).first() is not None
    return templates.TemplateResponse(
        request,
        "community.html",
        {
            "nav": region.code if region else "",
            "community": c,
            "region": region,
            "market_label": MARKET_LABEL.get(c.market_type, c.market_type),
            "stats": stats,
            "series": series,
            "listings": listings,
            "transactions": txns,
            "watched": watched,
            "lfilters": {
                "rooms": rooms,
                "price_min": price_min,
                "price_max": price_max,
                "unit_min": unit_min,
                "unit_max": unit_max,
                "area_min": area_min,
                "area_max": area_max,
            },
        },
    )


@app.get("/watchlist-page", response_class=HTMLResponse)
def page_watchlist(request: Request, db: Session = Depends(get_db)):
    rows = []
    for w in db.query(Watchlist).order_by(Watchlist.created_at.desc()).all():
        c = db.get(Community, w.community_id)
        r = db.get(Region, c.region_id) if c else None
        rows.append(
            {
                "community_id": w.community_id,
                "name": c.name if c else "?",
                "district": r.district if r else "",
                "market_type": c.market_type if c else "ershou",
                "market_label": MARKET_LABEL.get(c.market_type, "") if c else "",
                "note": w.note,
                "created_at": w.created_at,
            }
        )
    return templates.TemplateResponse(
        request, "watchlist.html", {"nav": "watch", "rows": rows}
    )


@app.post("/ui/watchlist/add/{community_id}")
def ui_watch_add(community_id: int, db: Session = Depends(get_db)):
    c = db.get(Community, community_id)
    if not c:
        raise HTTPException(404)
    if not db.query(Watchlist).filter_by(community_id=community_id).first():
        db.add(Watchlist(community_id=community_id, note="网页关注"))
        db.commit()
        refresh_community_snapshot(db, community_id)
        db.commit()
    return RedirectResponse(url=f"/communities/{community_id}", status_code=303)


@app.post("/ui/watchlist/remove/{community_id}")
def ui_watch_remove(community_id: int, db: Session = Depends(get_db)):
    w = db.query(Watchlist).filter_by(community_id=community_id).first()
    if w:
        db.delete(w)
        db.commit()
    ref = f"/communities/{community_id}"
    return RedirectResponse(url=ref, status_code=303)


# ---------- JSON API ----------

@app.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "communities": db.query(func.count(Community.id)).scalar(),
        "listings": db.query(func.count(Listing.id)).scalar(),
        "transactions": db.query(func.count(Transaction.id)).scalar(),
        "ershou_listings": db.query(func.count(Listing.id)).filter_by(market_type="ershou").scalar(),
        "xinfang_listings": db.query(func.count(Listing.id)).filter_by(market_type="xinfang").scalar(),
    }


@app.get("/api/regions", response_model=List[RegionOut])
@app.get("/regions", response_model=List[RegionOut], include_in_schema=False)
def list_regions_api(db: Session = Depends(get_db)):
    # /regions 已被 HTML 占用路径前缀；提供 /api/regions，并保留兼容查询
    return db.query(Region).all()


@app.get("/api/communities")
def list_communities_api(
    region: Optional[str] = None,
    market: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Community)
    if region:
        reg = db.query(Region).filter_by(code=region).first()
        if not reg:
            raise HTTPException(404, f"未知区域: {region}")
        query = query.filter(Community.region_id == reg.id)
    if market in ("ershou", "xinfang"):
        query = query.filter(Community.market_type == market)
    if q:
        query = query.filter(Community.name.contains(q))
    out = []
    for c in query.order_by(Community.id).limit(limit).all():
        r = db.get(Region, c.region_id)
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "region_id": c.region_id,
                "region_code": r.code if r else None,
                "region_district": r.district if r else None,
                "address": c.address,
                "area_name": c.area_name,
                "market_type": c.market_type,
                "property_type": c.property_type,
                "developer": c.developer,
                "build_year": c.build_year,
                "source": c.source,
                "avg_unit_price": latest_community_price(db, c.id),
                "detail_url": f"/communities/{c.id}",
            }
        )
    return out


@app.get("/api/communities/{community_id}")
def get_community_api(community_id: int, db: Session = Depends(get_db)):
    c = db.get(Community, community_id)
    if not c:
        raise HTTPException(404, "小区不存在")
    r = db.get(Region, c.region_id)
    return {
        "id": c.id,
        "name": c.name,
        "address": c.address,
        "area_name": c.area_name,
        "market_type": c.market_type,
        "property_type": c.property_type,
        "developer": c.developer,
        "build_year": c.build_year,
        "region_code": r.code if r else None,
        "region_district": r.district if r else None,
        "stats": community_detail_stats(db, community_id),
        "detail_url": f"/communities/{c.id}",
    }


@app.get("/api/communities/{community_id}/prices")
def community_prices_api(
    community_id: int,
    market: Optional[str] = None,
    db: Session = Depends(get_db),
):
    c = db.get(Community, community_id)
    if not c:
        raise HTTPException(404, "小区不存在")
    mt = market or c.market_type
    return community_price_series(db, community_id, market_type=mt)


@app.get("/api/listings")
def list_listings_api(
    region: Optional[str] = None,
    community_id: Optional[int] = None,
    market: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Listing)
    if region:
        reg = db.query(Region).filter_by(code=region).first()
        if not reg:
            raise HTTPException(404)
        query = query.filter(Listing.region_id == reg.id)
    if community_id:
        query = query.filter(Listing.community_id == community_id)
    if market in ("ershou", "xinfang"):
        query = query.filter(Listing.market_type == market)
    return query.order_by(Listing.scraped_at.desc()).limit(limit).all()


@app.get("/api/transactions")
def list_transactions_api(
    region: Optional[str] = None,
    community_id: Optional[int] = None,
    market: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Transaction)
    if region:
        reg = db.query(Region).filter_by(code=region).first()
        if not reg:
            raise HTTPException(404)
        query = query.filter(Transaction.region_id == reg.id)
    if community_id:
        query = query.filter(Transaction.community_id == community_id)
    if market in ("ershou", "xinfang"):
        query = query.filter(Transaction.market_type == market)
    return query.order_by(Transaction.deal_date.desc()).limit(limit).all()


@app.get("/stats/overview")
@app.get("/api/stats/overview")
def stats_overview(db: Session = Depends(get_db)):
    return overview_stats(db)


@app.get("/stats/compare")
@app.get("/api/stats/compare")
def stats_compare(db: Session = Depends(get_db)):
    return compare_regions(db)


@app.post("/watchlist", response_model=WatchlistOut)
@app.post("/api/watchlist", response_model=WatchlistOut)
def add_watchlist(body: WatchlistIn, db: Session = Depends(get_db)):
    c = db.get(Community, body.community_id)
    if not c:
        raise HTTPException(404, "小区不存在")
    existing = db.query(Watchlist).filter_by(community_id=body.community_id).first()
    if existing:
        if body.note is not None:
            existing.note = body.note
        db.commit()
        return WatchlistOut(
            id=existing.id,
            community_id=existing.community_id,
            note=existing.note,
            community_name=c.name,
            created_at=existing.created_at,
        )
    w = Watchlist(community_id=body.community_id, note=body.note)
    db.add(w)
    db.commit()
    db.refresh(w)
    refresh_community_snapshot(db, body.community_id)
    db.commit()
    return WatchlistOut(
        id=w.id,
        community_id=w.community_id,
        note=w.note,
        community_name=c.name,
        created_at=w.created_at,
    )


@app.get("/watchlist", response_model=List[WatchlistOut])
@app.get("/api/watchlist", response_model=List[WatchlistOut])
def get_watchlist(db: Session = Depends(get_db)):
    out = []
    for w in db.query(Watchlist).order_by(Watchlist.created_at.desc()).all():
        c = db.get(Community, w.community_id)
        out.append(
            WatchlistOut(
                id=w.id,
                community_id=w.community_id,
                note=w.note,
                community_name=c.name if c else None,
                created_at=w.created_at,
            )
        )
    return out
