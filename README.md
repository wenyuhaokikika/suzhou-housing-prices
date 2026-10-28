# 苏州市辖区房价采集与分析

本地项目：聚焦**苏州市辖区**二手房与新房挂牌/成交，写入 SQLite，支持小区跟踪、各区对比与 FastAPI 多页看板。

相关说明与迭代记录见个人博客：[https://wenyuhaokikika.github.io](https://wenyuhaokikika.github.io)

## 数据口径（重要）

- **主指标为成交单价**（含新房备案/成交口径）：总览、区对比、小区排序与走势图均以**成交均价**为主；挂牌价仅作参考，并展示「挂牌相对成交溢价」。
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

## 演示数据 vs 真实爬取

| 模式 | 命令要点 | 说明 |
|------|----------|------|
| **演示（推荐）** | `--demo-only` 或 `--demo` | 写入 `source=demo` 合成数据：真实可识别小区名 + 近 3 年趋势，保证端到端可用 |
| **真实站点** | `--source beike` / `anjuke` / `haohaoxuanfang` | 真实爬虫骨架；主流站点反爬严，易失败或需自行限速/代理，**勿默认依赖** |

不加 `--demo` 时仅尝试真实源；加 `--demo` 会先灌演示再尝试 live（`--source all` 时）。

## 安装

```bash
git clone https://github.com/wenyuhaokikika/suzhou-housing-prices.git
cd suzhou-housing-prices
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

可选：通过环境变量 `HOUSING_DB_URL` 指向其他 SQLite 路径（默认 `data/housing.db`）。

## 采集

```bash
# 灌满苏州六区演示数据（空库或重灌时推荐）
python -m scrapers.run --region all --demo-only

# 指定一区
python -m scrapers.run --region sip --demo-only

# 尝试真实站点（常被反爬，页数宜小）
python -m scrapers.run --region wuzhong --source beike --max-pages 2
```

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
| 某区列表 | http://127.0.0.1:8765/regions/wuzhong |
| 全部小区 | http://127.0.0.1:8765/communities |
| 小区详情 | http://127.0.0.1:8765/communities/1 |
| 关注 | http://127.0.0.1:8765/watchlist-page |
| 数据说明 | http://127.0.0.1:8765/about-data |

常用 JSON：`GET /health`、`GET /api/regions`、`GET /stats/overview`、`GET /stats/compare` 等（详见 `/docs`）。

## 目录结构

```
suzhou-housing-prices/
├── app/                 # FastAPI + 多页看板
├── scrapers/            # demo / beike / anjuke + suzhou_communities.py
├── analysis/
├── db/models.py
├── data/housing.db      # 演示库（可 --demo-only 重建）
├── data/report.json
└── requirements.txt
```

## 许可与免责

数据仅供学习与研究；演示与爬取结果不构成投资建议。使用真实爬虫请遵守目标站点 robots 与法律法规。
