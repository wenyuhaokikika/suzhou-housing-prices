"""房价预测模块：基于历史数据训练模型并预测未来房价

用法:
    python -m analysis.predict                    # 训练并保存模型、指标
    python -m analysis.predict --predict-months 6 # 预测未来 6 个月
    python -m analysis.predict --cv-only          # 仅运行交叉验证

模型:
    - Ridge 回归 (baseline)
    - RandomForest
    - GradientBoosting

使用时间感知划分:
    - 训练集: 早期数据 (前 70%)
    - 验证集: 中期数据 (中间 15%)
    - 测试集: 近期数据 (后 15%)
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.models import Community, PriceSnapshot, Region, get_session, init_db

DATA_DIR = os.path.join(ROOT, "data")
MODEL_PATH = os.path.join(DATA_DIR, "prediction_model.pkl")
SCALER_PATH = os.path.join(DATA_DIR, "prediction_scaler.pkl")
ENCODERS_PATH = os.path.join(DATA_DIR, "prediction_encoders.pkl")
METRICS_PATH = os.path.join(DATA_DIR, "prediction_metrics.json")


def load_training_data() -> pd.DataFrame:
    """从数据库加载训练数据：小区历史价格快照 + 特征"""
    init_db()
    session = get_session()
    try:
        snapshots = (
            session.query(
                PriceSnapshot.community_id,
                PriceSnapshot.snap_date,
                PriceSnapshot.avg_unit_price,
                PriceSnapshot.market_type,
                PriceSnapshot.sample_count,
            )
            .filter(PriceSnapshot.avg_unit_price.isnot(None))
            .order_by(PriceSnapshot.snap_date)
            .all()
        )
        communities = {
            c.id: {
                "region_id": c.region_id,
                "market_type": c.market_type,
                "build_year": c.build_year,
                "area_name": c.area_name,
                "property_type": c.property_type,
                "name": c.name,
            }
            for c in session.query(Community).all()
        }
        regions = {r.id: r.code for r in session.query(Region).all()}
    finally:
        session.close()

    rows = []
    for cid, snap_date, price, mtype, sample in snapshots:
        if cid not in communities:
            continue
        c = communities[cid]
        rows.append(
            {
                "community_id": cid,
                "community_name": c["name"],
                "snap_date": snap_date,
                "year": snap_date.year,
                "month": snap_date.month,
                "avg_unit_price": price,
                "market_type": mtype or c["market_type"],
                "region_code": regions.get(c["region_id"], "unknown"),
                "build_year": c["build_year"],
                "area_name": c["area_name"] or "未知",
                "property_type": c["property_type"] or "住宅",
                "sample_count": sample,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["snap_date"] = pd.to_datetime(df["snap_date"])
    df = df.sort_values(["community_id", "snap_date"])

    df["month_index"] = (
        (df["snap_date"].dt.year - df["snap_date"].dt.year.min()) * 12
        + df["snap_date"].dt.month
    )
    
    df["quarter"] = df["snap_date"].dt.quarter
    df["is_year_end"] = (df["month"] >= 11).astype(int)
    
    if df["build_year"].notna().sum() > 0:
        median_year = df["build_year"].median()
        df["build_year"] = df["build_year"].fillna(median_year)
        df["building_age"] = df["year"] - df["build_year"]
    else:
        df["build_year"] = 2015
        df["building_age"] = df["year"] - 2015

    df["lag_1"] = df.groupby("community_id")["avg_unit_price"].shift(1)
    df["lag_3"] = df.groupby("community_id")["avg_unit_price"].shift(3)
    df["lag_6"] = df.groupby("community_id")["avg_unit_price"].shift(6)
    df["lag_12"] = df.groupby("community_id")["avg_unit_price"].shift(12)

    df["rolling_mean_3"] = (
        df.groupby("community_id")["avg_unit_price"]
        .transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
    )
    df["rolling_mean_6"] = (
        df.groupby("community_id")["avg_unit_price"]
        .transform(lambda x: x.shift(1).rolling(6, min_periods=1).mean())
    )

    df["price_diff_1"] = df["lag_1"] - df.groupby("community_id")["avg_unit_price"].shift(2)
    df["price_diff_3"] = df["lag_1"] - df["lag_3"]

    df = df.dropna(subset=["lag_1"])

    return df


def prepare_features(
    df: pd.DataFrame,
    encoders: Optional[dict] = None,
    fit_encoders: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """准备特征矩阵和目标变量"""
    feature_cols = [
        "month_index",
        "month",
        "quarter",
        "is_year_end",
        "building_age",
        "lag_1",
        "lag_3",
        "rolling_mean_3",
        "rolling_mean_6",
        "price_diff_1",
    ]

    cat_cols = ["region_code", "market_type", "property_type"]

    if encoders is None:
        encoders = {}

    df_encoded = df.copy()
    for col in cat_cols:
        if fit_encoders or col not in encoders:
            le = LabelEncoder()
            df_encoded[col + "_enc"] = le.fit_transform(df_encoded[col].astype(str))
            encoders[col] = le
        else:
            le = encoders[col]
            df_encoded[col + "_enc"] = df_encoded[col].apply(
                lambda x: le.transform([str(x)])[0]
                if str(x) in le.classes_
                else len(le.classes_)
            )
        feature_cols.append(col + "_enc")

    for col in feature_cols:
        if col in df_encoded.columns:
            df_encoded[col] = df_encoded[col].fillna(df_encoded[col].median())

    X = df_encoded[feature_cols].values
    y = df_encoded["avg_unit_price"].values

    return X, y, encoders


def time_split(df: pd.DataFrame, train_ratio=0.7, val_ratio=0.15):
    """时间感知划分：按时间顺序划分训练/验证/测试集"""
    df_sorted = df.sort_values("snap_date")
    n = len(df_sorted)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train_df = df_sorted.iloc[:train_end]
    val_df = df_sorted.iloc[train_end:val_end]
    test_df = df_sorted.iloc[val_end:]

    return train_df, val_df, test_df


def evaluate_model(model, X, y, name: str) -> dict:
    """评估模型性能"""
    y_pred = model.predict(X)
    rmse = np.sqrt(mean_squared_error(y, y_pred))
    mae = mean_absolute_error(y, y_pred)
    r2 = r2_score(y, y_pred)
    mape = np.mean(np.abs((y - y_pred) / y)) * 100

    return {
        "name": name,
        "rmse": round(rmse, 2),
        "mae": round(mae, 2),
        "r2": round(r2, 4),
        "mape": round(mape, 2),
    }


def cross_validate_models(X, y, cv_splits=5) -> list[dict]:
    """对多个模型进行时间序列交叉验证"""
    models = [
        ("Ridge", Ridge(alpha=1.0)),
        ("RandomForest", RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)),
        ("GradientBoosting", GradientBoostingRegressor(n_estimators=100, max_depth=5, random_state=42)),
    ]

    tscv = TimeSeriesSplit(n_splits=cv_splits)
    results = []

    for name, model in models:
        neg_mse = cross_val_score(model, X, y, cv=tscv, scoring="neg_mean_squared_error")
        rmse_scores = np.sqrt(-neg_mse)
        neg_mae = cross_val_score(model, X, y, cv=tscv, scoring="neg_mean_absolute_error")
        mae_scores = -neg_mae
        r2_scores = cross_val_score(model, X, y, cv=tscv, scoring="r2")

        results.append(
            {
                "model": name,
                "cv_rmse_mean": round(rmse_scores.mean(), 2),
                "cv_rmse_std": round(rmse_scores.std(), 2),
                "cv_mae_mean": round(mae_scores.mean(), 2),
                "cv_mae_std": round(mae_scores.std(), 2),
                "cv_r2_mean": round(r2_scores.mean(), 4),
                "cv_r2_std": round(r2_scores.std(), 4),
            }
        )

    return results


def train_and_evaluate(save_model: bool = True) -> dict:
    """完整训练流程：加载数据、交叉验证、训练、评估、保存"""
    print("加载训练数据...")
    df = load_training_data()
    if df.empty:
        return {"error": "无可用训练数据"}

    print(f"数据量: {len(df)} 条记录, {df['community_id'].nunique()} 个小区")
    print(f"时间范围: {df['snap_date'].min().date()} ~ {df['snap_date'].max().date()}")

    train_df, val_df, test_df = time_split(df)
    print(f"划分: 训练={len(train_df)}, 验证={len(val_df)}, 测试={len(test_df)}")

    X_train, y_train, encoders = prepare_features(train_df, fit_encoders=True)
    X_val, y_val, _ = prepare_features(val_df, encoders=encoders, fit_encoders=False)
    X_test, y_test, _ = prepare_features(test_df, encoders=encoders, fit_encoders=False)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    print("\n==== 交叉验证 (5-fold Time Series CV) ====")
    X_all, y_all, _ = prepare_features(df, encoders=encoders, fit_encoders=False)
    X_all_scaled = scaler.fit_transform(X_all)
    cv_results = cross_validate_models(X_all_scaled, y_all)
    for r in cv_results:
        print(f"{r['model']:20} RMSE={r['cv_rmse_mean']:.1f}±{r['cv_rmse_std']:.1f}  "
              f"MAE={r['cv_mae_mean']:.1f}±{r['cv_mae_std']:.1f}  R²={r['cv_r2_mean']:.4f}±{r['cv_r2_std']:.4f}")

    best_cv = min(cv_results, key=lambda x: x["cv_rmse_mean"])
    print(f"\n最佳 CV 模型: {best_cv['model']} (RMSE={best_cv['cv_rmse_mean']})")

    print("\n==== 训练最终模型 ====")
    models = {
        "Ridge": Ridge(alpha=1.0),
        "RandomForest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1),
        "GradientBoosting": GradientBoostingRegressor(n_estimators=100, max_depth=5, random_state=42),
    }

    train_results = []
    val_results = []
    test_results = []

    for name, model in models.items():
        model.fit(X_train_scaled, y_train)
        train_results.append(evaluate_model(model, X_train_scaled, y_train, name))
        val_results.append(evaluate_model(model, X_val_scaled, y_val, name))
        test_results.append(evaluate_model(model, X_test_scaled, y_test, name))

    print("\n验证集结果:")
    for r in val_results:
        print(f"  {r['name']:20} RMSE={r['rmse']:.1f}  MAE={r['mae']:.1f}  R²={r['r2']:.4f}  MAPE={r['mape']:.2f}%")

    print("\n测试集结果:")
    for r in test_results:
        print(f"  {r['name']:20} RMSE={r['rmse']:.1f}  MAE={r['mae']:.1f}  R²={r['r2']:.4f}  MAPE={r['mape']:.2f}%")

    best_test = min(test_results, key=lambda x: x["rmse"])
    chosen_model_name = best_test["name"]
    print(f"\n选定模型: {chosen_model_name} (测试集 RMSE={best_test['rmse']}, R²={best_test['r2']})")

    final_model = models[chosen_model_name]
    final_model.fit(X_all_scaled, y_all)

    metrics = {
        "generated_at": date.today().isoformat(),
        "data_summary": {
            "total_records": len(df),
            "communities": df["community_id"].nunique(),
            "date_range": {
                "start": df["snap_date"].min().strftime("%Y-%m-%d"),
                "end": df["snap_date"].max().strftime("%Y-%m-%d"),
            },
            "split": {
                "train": len(train_df),
                "validation": len(val_df),
                "test": len(test_df),
            },
        },
        "cross_validation": cv_results,
        "train_results": train_results,
        "validation_results": val_results,
        "test_results": test_results,
        "chosen_model": {
            "name": chosen_model_name,
            "reason": f"测试集上 RMSE 最低 ({best_test['rmse']}), R² 为 {best_test['r2']}, MAPE 为 {best_test['mape']}%",
        },
        "final_metrics": best_test,
    }

    if save_model:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(final_model, f)
        with open(SCALER_PATH, "wb") as f:
            pickle.dump(scaler, f)
        with open(ENCODERS_PATH, "wb") as f:
            pickle.dump(encoders, f)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        print(f"\n模型已保存: {MODEL_PATH}")
        print(f"指标已保存: {METRICS_PATH}")

    return metrics


def load_model():
    """加载已训练的模型"""
    if not os.path.exists(MODEL_PATH):
        return None, None, None
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(SCALER_PATH, "rb") as f:
        scaler = pickle.load(f)
    with open(ENCODERS_PATH, "rb") as f:
        encoders = pickle.load(f)
    return model, scaler, encoders


def load_metrics() -> Optional[dict]:
    """加载保存的指标"""
    if not os.path.exists(METRICS_PATH):
        return None
    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def predict_community_future(
    community_id: int,
    months_ahead: int = 6,
) -> list[dict]:
    """预测指定小区未来房价"""
    model, scaler, encoders = load_model()
    if model is None:
        raise ValueError("模型未训练，请先运行 python -m analysis.predict")

    init_db()
    session = get_session()
    try:
        community = session.get(Community, community_id)
        if not community:
            raise ValueError(f"小区 {community_id} 不存在")

        region = session.get(Region, community.region_id)
        region_code = region.code if region else "unknown"

        snapshots = (
            session.query(PriceSnapshot)
            .filter(PriceSnapshot.community_id == community_id)
            .order_by(PriceSnapshot.snap_date.desc())
            .limit(12)
            .all()
        )

        if len(snapshots) < 3:
            raise ValueError(f"小区历史数据不足 (仅 {len(snapshots)} 条)")

        snapshots = sorted(snapshots, key=lambda x: x.snap_date)
        prices = [s.avg_unit_price for s in snapshots]
        last_snap = snapshots[-1]
        last_date = last_snap.snap_date

        community_info = {
            "community_id": community_id,
            "community_name": community.name,
            "region_code": region_code,
            "market_type": community.market_type,
            "build_year": community.build_year or 2015,
            "property_type": community.property_type or "住宅",
        }
    finally:
        session.close()

    predictions = []
    current_prices = list(prices)

    for i in range(1, months_ahead + 1):
        pred_date = last_date + timedelta(days=30 * i)
        if isinstance(pred_date, date) and not hasattr(pred_date, "hour"):
            pred_date = pred_date
        pred_year = pred_date.year if hasattr(pred_date, "year") else last_date.year + (i // 12)
        pred_month = ((last_date.month + i - 1) % 12) + 1

        features = {
            "month_index": (pred_year - 2023) * 12 + pred_month,
            "month": pred_month,
            "quarter": (pred_month - 1) // 3 + 1,
            "is_year_end": 1 if pred_month >= 11 else 0,
            "building_age": pred_year - community_info["build_year"],
            "lag_1": current_prices[-1] if current_prices else 0,
            "lag_3": current_prices[-3] if len(current_prices) >= 3 else current_prices[0],
            "rolling_mean_3": np.mean(current_prices[-3:]) if len(current_prices) >= 3 else current_prices[-1],
            "rolling_mean_6": np.mean(current_prices[-6:]) if len(current_prices) >= 6 else np.mean(current_prices),
            "price_diff_1": (current_prices[-1] - current_prices[-2]) if len(current_prices) >= 2 else 0,
        }

        for col in ["region_code", "market_type", "property_type"]:
            le = encoders.get(col)
            val = community_info.get(col, "unknown")
            if le and str(val) in le.classes_:
                features[col + "_enc"] = le.transform([str(val)])[0]
            else:
                features[col + "_enc"] = 0

        feature_order = [
            "month_index", "month", "quarter", "is_year_end", "building_age",
            "lag_1", "lag_3", "rolling_mean_3", "rolling_mean_6", "price_diff_1",
            "region_code_enc", "market_type_enc", "property_type_enc",
        ]
        X = np.array([[features.get(f, 0) for f in feature_order]])
        X_scaled = scaler.transform(X)
        pred_price = model.predict(X_scaled)[0]

        predictions.append({
            "date": f"{pred_year:04d}-{pred_month:02d}-01",
            "predicted_price": round(pred_price, 1),
            "months_ahead": i,
        })

        current_prices.append(pred_price)
        if len(current_prices) > 12:
            current_prices = current_prices[-12:]

    return predictions


def get_prediction_summary(community_id: int, months: int = 6) -> dict:
    """获取小区预测摘要"""
    init_db()
    session = get_session()
    try:
        community = session.get(Community, community_id)
        if not community:
            return {"error": f"小区 {community_id} 不存在"}

        region = session.get(Region, community.region_id)

        snapshots = (
            session.query(PriceSnapshot)
            .filter(PriceSnapshot.community_id == community_id)
            .order_by(PriceSnapshot.snap_date.desc())
            .limit(24)
            .all()
        )
        history = [
            {"date": s.snap_date.isoformat(), "price": s.avg_unit_price}
            for s in sorted(snapshots, key=lambda x: x.snap_date)
        ]
    finally:
        session.close()

    try:
        predictions = predict_community_future(community_id, months)
    except ValueError as e:
        return {"error": str(e)}

    current_price = history[-1]["price"] if history else None
    future_price = predictions[-1]["predicted_price"] if predictions else None
    change_pct = None
    if current_price and future_price:
        change_pct = round((future_price - current_price) / current_price * 100, 2)

    return {
        "community": {
            "id": community_id,
            "name": community.name,
            "region": region.district if region else "未知",
            "region_code": region.code if region else "unknown",
            "market_type": community.market_type,
        },
        "current_price": current_price,
        "history": history,
        "predictions": predictions,
        "summary": {
            "months_predicted": months,
            "predicted_price": future_price,
            "change_pct": change_pct,
            "trend": "上涨" if change_pct and change_pct > 1 else ("下跌" if change_pct and change_pct < -1 else "持平"),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="房价预测模型训练与预测")
    parser.add_argument("--cv-only", action="store_true", help="仅运行交叉验证")
    parser.add_argument("--predict-months", type=int, default=0, help="预测未来 N 个月")
    parser.add_argument("--community", type=int, help="指定小区 ID 进行预测")
    args = parser.parse_args()

    if args.predict_months > 0 and args.community:
        try:
            result = get_prediction_summary(args.community, args.predict_months)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"预测失败: {e}")
        return

    metrics = train_and_evaluate(save_model=not args.cv_only)

    if "error" in metrics:
        print(f"错误: {metrics['error']}")
        return

    print("\n======== 训练完成 ========")


if __name__ == "__main__":
    main()
