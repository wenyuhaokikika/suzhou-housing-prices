"""SQLite 数据模型：区域、小区、挂牌、成交、价格快照、爬取任务、关注列表"""
from __future__ import annotations

import os
from datetime import datetime, date
from typing import Optional, Generator

from sqlalchemy import (
    create_engine,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    Date,
    ForeignKey,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
    Session,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "housing.db")
DATABASE_URL = os.environ.get("HOUSING_DB_URL", f"sqlite:///{DEFAULT_DB_PATH}")


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(50), nullable=False)
    district: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    communities: Mapped[list["Community"]] = relationship(back_populates="region")

    __table_args__ = (UniqueConstraint("city", "district", name="uq_city_district"),)


class Community(Base):
    """小区 / 楼盘"""
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    area_name: Mapped[Optional[str]] = mapped_column(String(100))  # 片区：越溪/南桥等
    market_type: Mapped[str] = mapped_column(String(20), default="ershou")  # ershou / xinfang
    property_type: Mapped[Optional[str]] = mapped_column(String(50), default="住宅")
    developer: Mapped[Optional[str]] = mapped_column(String(100))
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    build_year: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    source_id: Mapped[Optional[str]] = mapped_column(String(100))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    region: Mapped["Region"] = relationship(back_populates="communities")
    listings: Mapped[list["Listing"]] = relationship(back_populates="community")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="community")
    snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="community")

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_community_source"),
        Index("ix_community_name", "name"),
        Index("ix_community_region", "region_id"),
        Index("ix_community_market", "market_type"),
    )


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    community_id: Mapped[Optional[int]] = mapped_column(ForeignKey("communities.id"))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    listing_type: Mapped[str] = mapped_column(String(20), default="sale")  # sale / rent
    market_type: Mapped[str] = mapped_column(String(20), default="ershou")  # ershou / xinfang
    title: Mapped[Optional[str]] = mapped_column(String(500))
    price: Mapped[Optional[float]] = mapped_column(Float)
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    area: Mapped[Optional[float]] = mapped_column(Float)
    rooms: Mapped[Optional[str]] = mapped_column(String(50))
    floor: Mapped[Optional[str]] = mapped_column(String(50))
    orientation: Mapped[Optional[str]] = mapped_column(String(50))
    build_year: Mapped[Optional[int]] = mapped_column(Integer)
    decoration: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    raw_json: Mapped[Optional[str]] = mapped_column(Text)

    community: Mapped[Optional["Community"]] = relationship(back_populates="listings")

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_listing_source"),
        Index("ix_listing_region", "region_id"),
        Index("ix_listing_community", "community_id"),
        Index("ix_listing_market", "market_type"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    community_id: Mapped[Optional[int]] = mapped_column(ForeignKey("communities.id"))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    market_type: Mapped[str] = mapped_column(String(20), default="ershou")
    deal_date: Mapped[Optional[date]] = mapped_column(Date)
    price: Mapped[Optional[float]] = mapped_column(Float)
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    area: Mapped[Optional[float]] = mapped_column(Float)
    rooms: Mapped[Optional[str]] = mapped_column(String(50))
    floor: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    raw_json: Mapped[Optional[str]] = mapped_column(Text)

    community: Mapped[Optional["Community"]] = relationship(back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_txn_source"),
        Index("ix_txn_region", "region_id"),
        Index("ix_txn_community", "community_id"),
        Index("ix_txn_date", "deal_date"),
        Index("ix_txn_market", "market_type"),
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    market_type: Mapped[str] = mapped_column(String(20), default="ershou")
    avg_unit_price: Mapped[Optional[float]] = mapped_column(Float)
    median_unit_price: Mapped[Optional[float]] = mapped_column(Float)
    min_unit_price: Mapped[Optional[float]] = mapped_column(Float)
    max_unit_price: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(50), default="computed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    community: Mapped["Community"] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("community_id", "snap_date", "source", "market_type", name="uq_snap"),
        Index("ix_snap_date", "snap_date"),
        Index("ix_snap_market", "market_type"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region_code: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(20), default="live")
    status: Mapped[str] = mapped_column(String(20), default="running")
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    listings_upserted: Mapped[int] = mapped_column(Integer, default=0)
    txns_upserted: Mapped[int] = mapped_column(Integer, default=0)
    communities_upserted: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id"), unique=True, nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


_engine = None
_SessionLocal = None


def get_engine(db_url: str | None = None):
    global _engine, _SessionLocal
    url = db_url or DATABASE_URL
    if _engine is None or (db_url and db_url != DATABASE_URL):
        os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)
        _engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def reset_engine():
    """强制重建引擎（删库后调用）"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_session(db_url: str | None = None) -> Session:
    get_engine(db_url)
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db(db_url: str | None = None) -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    session = get_session(db_url)
    try:
        defaults = [
            ("苏州", "姑苏", "gusu"),
            ("苏州", "虎丘", "huqiu"),
            ("苏州", "吴中", "wuzhong"),
            ("苏州", "相城", "xiangcheng"),
            ("苏州", "吴江", "wujiang"),
            ("苏州", "工业园区", "sip"),
        ]
        for city, district, code in defaults:
            exists = session.query(Region).filter_by(code=code).first()
            if not exists:
                session.add(Region(city=city, district=district, code=code))
        session.commit()
    finally:
        session.close()


def session_scope(db_url: str | None = None) -> Generator[Session, None, None]:
    session = get_session(db_url)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
