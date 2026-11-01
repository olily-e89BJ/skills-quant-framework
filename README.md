# Skills 股票量化分析框架

面向 A 股的 Python 量化分析框架，覆盖数据获取 → 指标计算 → 信号生成 → 回测验证 → 参数优化 → 组合管理全流程。

---

## 免责声明

本项目为测试项目，算法产出仅供参考，不构成投资建议。
**投资有风险，入市需谨慎！**

## 概览

- **50+ 模块**（`.claude/skills/` 43 个 + `core/` 9 个），约 28,500 行 Python
- **990 个离线测试**（`python3 -m pytest tests/ -q`，全程无需联网）
- **数据本地缓存**（Parquet + CSV 降级），复权口径入库
- **Web 界面**（Streamlit，可选依赖）
- 交易规则建模：t+1 成交、涨跌停限制、手续费/印花税、成交容量约束、停牌识别

## 快速开始

### 安装

```bash
# 分析层（必需）
pip install -r .claude/skills/requirements.txt

# Web 界面（可选）
pip install -r web_requirements.txt
```

核心依赖：`pandas` `numpy` `scipy` `akshare`。可选：`pyarrow`（Parquet 缓存）、`matplotlib`（绘图）、`scikit-learn`（ML 预测）、`streamlit`（Web）。可选依赖缺失时对应功能降级，核心流程不受影响。

### 从信号到回测

```python
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator
from backtest_framework import BacktestEngine

# 取数（默认后复权，本地缓存优先）
fetcher = StockDataFetcher()
data = fetcher.get_quote_data("600519", days=252)

# 生成信号
data = SignalGenerator().generate_signals(data)
print(data.iloc[-1][["signal_buy", "signal_sell", "signal_strength"]])

# 回测
engine = BacktestEngine(initial_cash=100_000)
result = engine.run(data, strategy=lambda d: 1 if d.iloc[-1].get("signal_buy") else 0)
print(result["total_return"])
```

### Web 应用

```bash
python run_web_app.py        # http://localhost:8501
```

页面：仪表盘 / 数据分析 / 策略回测 / 组合管理 / 实时监控 / 历史验证。

## 模块索引

按分层组织，各层职责边界与契约见 [docs/skills_layers.md](docs/skills_layers.md)，完整 API 见 [API_REFERENCE.md](API_REFERENCE.md)。

### 数据层

| 模块 | 职责 |
|------|------|
| `stock_data_fetcher` | 历史行情 / 实时行情 / 财务数据取数入口 |
| `historical_data_manager` | 本地 Parquet 缓存、复权口径入库、增量更新、CLI |
| `realtime_quote` | 腾讯接口批量实时行情 |
| `sina_daily` | 新浪日线直连（含北交所） |
| `delisted_stocks` | 退市股清单与历史行情（幸存者偏差消除） |
| `data_cleaner` | 存量数据单位归一与结构清洗 |
| `stock_list_manager` | 股票清单与名称查询 |
| `js_runtime` | V8 解密闸门（新浪 KLC 载荷），批量取数线程安全 |

### 指标层（`core/`）

| 模块 | 职责 |
|------|------|
| `core/indicators` | RSI / ATR / MA / EMA / MACD / KDJ / BOLL / VWAP / OBV 公式单一真相源 |
| `core/indicator_engine` | 指标引擎（规范列名 + 历史列名双向映射） |
| `core/metrics` | 回测指标口径（胜率 / 盈亏比 / 回撤 / 夏普 / 连胜连亏） |
| `core/dataframe` | 日线列名标准化与涨跌幅派生 |
| `core/trading_calendar` | 交易日历（由指数行情反推）与停牌识别 |
| `core/signal` / `core/fetch_result` | 信号契约 / 取数结果契约 |
| `core/suspension` | 回测引擎停牌建模（共享实现） |

### 选股层（横截面，回答"买什么"）

| 模块 | 职责 |
|------|------|
| `multi_factor_selection` | 多因子选股（point-in-time 公告日过滤，z-score 打分） |
| `factor_library` | 原始因子计算单一真相源 |
| `stock_selector` | 绝对评分选股（0-100 分） |
| `long_term_selector` | 基本面长期持仓候选 |

### 择时与信号层（时序，回答"何时买卖"）

| 模块 | 职责 |
|------|------|
| `signal_generator` | 唯一信号打分实现（7 分项 + 互斥买卖信号） |
| `daily_signal_generator` | 体制检测 + 按体制选参 + 批量日报 |
| `reversal_detector` / `reversal_rules` | 反转规则（实盘/回测共用） |
| `market_regime_classifier` | 市场状态分类 |
| `technical_analyzer` | 单股综合技术分析报告 |
| `ml_predictor` | ML 涨跌预测 |

### 回测与优化层

| 模块 | 职责 |
|------|------|
| `backtest_framework` | 引擎 A：逐笔事件驱动 |
| `vectorized_backtest` | 引擎 B：向量化 + 日频盯市权益曲线 |
| `reversal_backtest` | 引擎 D：反转策略专用 |
| `optimization_engine` | GA 参数优化（IS/OOS 隔离、证据化 confidence） |
| `historical_backtest_validator` | 历史验证链（样本外隔离检查） |
| `strategy_optimizer` | 策略模板参数搜索（网格/随机/边界采样） |
| `execution_model` | t+1 成交、涨跌停、费用（四引擎共用） |
| `trade_constraints` | 下单前约束检查 |

### 执行、风控与展示层

| 模块 | 职责 |
|------|------|
| `portfolio_manager` | 组合持仓、集中度/现金闸门、再平衡 |
| `risk_management` | 止损管理、组合风险监控 |
| `position_analyzer` | 单股持仓分析（盈亏/技术状态） |
| `real_time_monitor` | 实时监控与告警 |
| `chart_visualizer` | K 线 / 指标 / 回测图表 |
| `web_app` | Streamlit 界面 |
| `quant_workflow` | 分析流程编排入口 |

## 文档导航

| 文档 | 内容 |
|------|------|
| [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) | 上手教程 |
| [API_REFERENCE.md](API_REFERENCE.md) | 按分层组织的完整 API |
| [docs/skills_layers.md](docs/skills_layers.md) | 分层架构、指标口径、列名契约 |
| [docs/USER_MANUAL_V2.md](docs/USER_MANUAL_V2.md) | 使用手册 |
| [docs/USAGE_EXAMPLES.md](docs/USAGE_EXAMPLES.md) | 使用示例 |
| [docs/ANALYSIS_WORKFLOW.md](docs/ANALYSIS_WORKFLOW.md) | 分析流程说明 |
| [docs/FAQ.md](docs/FAQ.md) | 常见问题 |
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | 部署指南 |
| [CHANGELOG.md](CHANGELOG.md) | 版本记录 |

## 项目结构

```
.
├── .claude/skills/          # 全部分析模块（按裸模块名导入）
│   ├── core/                # 指标/指标口径/契约/日历（单一真相源）
│   ├── config/              # 外置参数（因子权重、选择器阈值等）
│   ├── tools/pack.py        # 离线部署包构建脚本
│   ├── stock_list.csv       # 股票清单
│   └── requirements.txt     # 分析层依赖
├── tests/                   # 990 个离线测试
├── stock_data/              # 本地数据缓存（Parquet/CSV）
├── docs/                    # 架构与使用文档
├── run_web_app.py           # Web 启动入口
├── API_REFERENCE.md
├── README.md
└── AGENTS.md / CLAUDE.md    # agent 工作约定
```

所有模块以裸模块名互相导入（`from stock_data_fetcher import ...`），**必须从仓库根目录运行**。

## 测试

```bash
python3 -m pytest tests/ -q     # 990 个测试，全部离线
```

CI 在 push/PR 时自动运行（Python 3.11/3.12 矩阵）。

## 许可证

MIT License
