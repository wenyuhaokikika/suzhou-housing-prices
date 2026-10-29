# 苏州房价预测工具

基于机器学习的苏州市辖区房价预测与分析工具，支持历史数据可视化、多模型对比和未来价格预测。

相关说明与迭代记录见个人博客：[https://wenyuhaokikika.github.io](https://wenyuhaokikika.github.io)

## 功能特性

### 🔮 房价预测（新增）
- **多模型对比**：Ridge 回归、随机森林、梯度提升三种模型自动选优
- **时间感知划分**：训练集（早期 70%）→ 验证集（15%）→ 测试集（近期 15%）
- **5 折时间序列交叉验证**：使用 `TimeSeriesSplit` 保证时序一致性
- **丰富特征工程**：滞后价格、滚动均值、价格变化趋势、区域/类型编码
- **预测指标**：RMSE、MAE、R²、MAPE，保存至 `data/prediction_metrics.json`

### 📊 数据看板
- 六区房价总览与对比（姑苏/虎丘/吴中/相城/吴江/工业园区）
- 小区详情与历史走势图
- 成交均价为主、挂牌价为辅的双指标体系
- 关注列表与数据筛选

## 数据口径（重要）

- **主指标为成交单价**（含新房备案/成交口径）：总览、区对比、小区排序与走势图均以**成交均价**为主；挂牌价仅作参考。
- 仓库自带 `data/housing.db`（约 10MB 演示库）与 `data/report.json`，克隆即可启动 Web；无需先跑爬虫。
- 若需空库或刷新数据，见下方「采集」中的 `--demo-only`。

## 覆盖范围

**纳入（6 区）：** 姑苏、虎丘（含高新区语境）、吴中、相城、吴江、苏州工业园区  

**排除：** 张家港、常熟、太仓、昆山等**县级市**；以及外省市数据。

| code | 区 |
|------|----|
| `gusu` | 姑苏 |
| `huqiu` | 虎丘 |
| `wuzhong` | 吴中 |
| `xiangcheng` | 相城 |
| `wujiang` | 吴江 |
| `sip` | 工业园区 |

## 安装

```bash
git clone https://github.com/wenyuhaokikika/suzhou-housing-prices.git
cd suzhou-housing-prices
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

可选：通过环境变量 `HOUSING_DB_URL` 指向其他 SQLite 路径（默认 `data/housing.db`）。

## 训练预测模型

```bash
# 训练模型并保存（自动选择最优模型）
python -m analysis.predict

# 仅运行交叉验证（不保存模型）
python -m analysis.predict --cv-only

# 预测指定小区未来 6 个月房价
python -m analysis.predict --community 1 --predict-months 6
```

训练完成后：
- 模型保存至 `data/prediction_model.pkl`
- 指标保存至 `data/prediction_metrics.json`
- 网页端 `/predict` 页面可进行交互式预测

### 模型选择说明

本工具比较三种模型：
1. **Ridge 回归**：线性基线模型，适合捕捉整体趋势
2. **随机森林**：集成学习，对非线性关系有较好表现
3. **梯度提升**：通常在表格数据上表现最优

最终选择测试集 RMSE 最低的模型。典型结果：
- 梯度提升在大多数情况下表现最好
- R² > 0.99 表明模型能解释超过 99% 的价格变异
- MAPE < 1% 表明预测误差相对较小

## 采集

```bash
# 灌满苏州六区演示数据（空库或重灌时推荐）
python -m scrapers.run --region all --demo-only

# 指定一区
python -m scrapers.run --region sip --demo-only

# 尝试真实站点（常被反爬，页数宜小）
python -m scrapers.run --region wuzhong --source beike --max-pages 2
```

| 模式 | 命令要点 | 说明 |
|------|----------|------|
| **演示（推荐）** | `--demo-only` 或 `--demo` | 写入 `source=demo` 合成数据：真实可识别小区名 + 近 3 年趋势，保证端到端可用 |
| **真实站点** | `--source beike` / `anjuke` / `haohaoxuanfang` | 真实爬虫骨架；主流站点反爬严，易失败或需自行限速/代理，**勿默认依赖** |

## 分析 / 关注

```bash
python -m analysis.report          # 摘要写入 data/report.json
python -m analysis.watch --add 1 --note "关注"
```

## 启动 Web

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

浏览器打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/) 查看总览；API 文档见 [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)。

| 页面 | URL |
|------|-----|
| 总览 | http://127.0.0.1:8765/ |
| **房价预测** | http://127.0.0.1:8765/predict |
| 某区列表 | http://127.0.0.1:8765/regions/wuzhong |
| 全部小区 | http://127.0.0.1:8765/communities |
| 小区详情 | http://127.0.0.1:8765/communities/1 |
| 关注 | http://127.0.0.1:8765/watchlist-page |
| 数据说明 | http://127.0.0.1:8765/about-data |

### 预测 API

```bash
# 获取模型指标
curl http://127.0.0.1:8765/api/predict/metrics

# 预测小区房价（默认 6 个月）
curl http://127.0.0.1:8765/api/predict/1

# 预测 12 个月
curl "http://127.0.0.1:8765/api/predict/1?months=12"
```

## 目录结构

```
suzhou-housing-prices/
├── app/                 # FastAPI + 多页看板
│   └── templates/
│       └── predict.html # 预测页面
├── scrapers/            # demo / beike / anjuke + suzhou_communities.py
├── analysis/
│   ├── predict.py       # 房价预测模型（新增）
│   ├── report.py
│   ├── trends.py
│   └── watch.py
├── db/models.py
├── data/
│   ├── housing.db               # 演示库
│   ├── report.json
│   ├── prediction_model.pkl     # 训练后的模型
│   ├── prediction_scaler.pkl    # 特征缩放器
│   ├── prediction_encoders.pkl  # 类别编码器
│   └── prediction_metrics.json  # CV 和测试指标
└── requirements.txt
```

## 技术栈

- **后端**：FastAPI + SQLAlchemy + SQLite
- **前端**：Jinja2 模板 + Chart.js
- **机器学习**：scikit-learn（Ridge / RandomForest / GradientBoosting）
- **数据处理**：pandas + numpy

## 许可与免责

⚠️ **重要声明**：

1. 本工具仅供**学习与研究**使用
2. 预测结果**不构成任何投资建议**
3. 房价受政策、经济、供需等多因素影响，机器学习模型无法完全预测
4. 演示数据为合成数据，并非真实市场数据
5. 使用真实爬虫请遵守目标站点 robots 协议与相关法律法规

**请谨慎参考预测结果，做出任何购房/投资决策前请咨询专业人士。**
