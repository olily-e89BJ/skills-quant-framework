# Skills 量化分析框架 API 参考

按分层组织（数据层 → 指标层 → 信号/选股层 → 回测/优化层 → 执行/风控层 → UI）。列名与指标口径契约见 `docs/skills_layers.md`。

所有模块位于 `.claude/skills/`，按裸模块名导入，**从仓库根目录运行**（依赖 `sys.path` 相对路径）。

---

## 1. 数据层

### 1.1 StockDataFetcher（`stock_data_fetcher.py`）

历史行情、实时行情、财务数据的取数入口。取数默认走本地缓存（`stock_data/`），缺失时联网回补。

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher(data_dir="./stock_data")
```

#### get_quote_data()

```python
df = fetcher.get_quote_data(symbol="600519", days=252, adjust="hfq")
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| symbol | str | — | 6 位股票代码 |
| start_date / end_date | str/datetime | None | 与 days 二选一 |
| days | int | 252 | 回溯自然日数 |
| adjust | str | `"hfq"` | 复权口径：`"hfq"` 后复权（默认）/ `"qfq"` 前复权 / `""` 不复权。缺失口径返回空 DataFrame，不用其他口径冒充 |

返回列：`日期, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 涨跌幅`（标准列名映射见 `core/dataframe.OHLCV_COLUMN_MAP`）。

默认后复权的理由：后复权历史价不随新分红变化，增量缓存追加永远正确；前复权每次分红要重算全部历史。**需要真实成交价的场景**（持仓成本对比、实时告警）必须显式传 `adjust=""`。

#### get_quote_result()

同 `get_quote_data`，但返回 `core.fetch_result.FetchResult`（`ok/data/error/source/as_of/adjust`）。失败时 `ok=False` 且带 `error`，不会静默返回空表。

#### 其他方法

| 方法 | 说明 |
|------|------|
| `get_realtime_quote(symbol)` | 单股实时快照（腾讯行情） |
| `get_realtime_quotes_batch(symbols)` | 批量实时快照 |
| `batch_get_quotes(symbols, start_date=None, end_date=None, delay=0.5)` | 批量历史行情，返回 `{symbol: DataFrame}` |
| `get_financial_indicator(symbol, indicator="按年度")` | 财务指标（含公告日，供 point-in-time 过滤） |
| `get_stock_money_flow(symbol)` | 资金流 |
| `calculate_technical_indicators(df)` | 在 DataFrame 上追加常用技术指标列 |

### 1.2 HistoricalDataManager（`historical_data_manager.py`）

本地 Parquet/CSV 缓存的统一读写层（复权口径入库、元数据、增量更新、指数独立命名空间）。业务模块统一走 `get_daily_result()` 取数，不要自行联网。

CLI（从仓库根目录）：

```bash
python .claude/skills/historical_data_manager.py fetch 600519 --adjust hfq
python .claude/skills/historical_data_manager.py batch --adjust hfq
python .claude/skills/historical_data_manager.py delisted {refresh,status,fetch}
```

### 1.3 其他数据模块

| 模块 | 职责 |
|------|------|
| `realtime_quote.py` | 腾讯 `qt.gtimg.cn` 批量实时行情解析 |
| `sina_daily.py` | 新浪日线直连（含北交所、klc 加密载荷解码，经 `js_runtime` V8 闸门） |
| `delisted_stocks.py` | 沪深退市股清单与历史行情补齐（幸存者偏差证据） |
| `data_cleaner.py` | 存量数据单位归一与结构清洗 |
| `stock_list_manager.py` | 股票清单（`stock_list.csv`）与名称查询 |

---

## 2. 指标层（`core/`）

公式单一真相源在 `core/indicators.py`；业务模块通过 `core/indicator_engine.IndicatorEngine` 调用，不得内联重写公式。

```python
from core.indicators import rsi, atr, macd, kdj, bollinger, vwap
from core.indicator_engine import IndicatorEngine

eng = IndicatorEngine(df)                    # df 含 收盘/最高/最低/成交量
df["DIF"], df["DEA"], df["HIST"] = eng.macd()
```

| 指标 | 函数 | 口径 |
|------|------|------|
| RSI | `rsi(close, period=14)` | Cutler SMA 平滑；窗口内无下跌→100，无波动→50 |
| ATR | `atr(high, low, close, period=14)` | Wilder RMA，α=1/period |
| MA/EMA | `sma` / `ema` | EMA 为递归口径（`ewm(span, adjust=False)`） |
| MACD | `macd(close, fast, slow, signal)` | DIF=EMA(f)-EMA(s)；DEA=EMA(signal)(DIF)；HIST=DIF-DEA（不乘 2） |
| KDJ | `kdj(high, low, close, n=9)` | RSV→EMA(span=3, α=0.5)→K/D；J=3K-2D |
| BOLL | `bollinger(close, period=20, mult=2)` | mid=SMA；std 用样本标准差（ddof=1） |
| VWAP | `vwap(high, low, close, volume)` | 累积口径：`cumsum(TP·V)/cumsum(V)`，锚定序列起点 |
| OBV | `obv(close, volume)` | 按涨跌方向累加成交量 |

规范列名（`IndicatorEngine.to_legacy/to_canonical` 双向映射）：`MA{p} / EMA{p} / DIF / DEA / HIST / RSI / K / D / J / BB_* / TR / ATR / Vol_MA{p} / VWAP / OBV`。

回测指标口径在 `core/metrics.py`：`profit_factor`（求和式）、`max_drawdown_pct`（正值百分比）、`sharpe_ratio`（rf=0.03, ddof=1）、`win_rate`（盈利笔/全部笔，持平计分母不算赢）、`consecutive_streaks`（交易序列口径）。

---

## 3. 信号与选股层

### 3.1 SignalGenerator（`signal_generator.py`）

全项目唯一的信号打分实现（日频，单股）。

```python
from signal_generator import SignalGenerator

gen = SignalGenerator()
df = gen.generate_signals(data)          # 追加 7 个 tier 分项 + 信号列
latest = gen.get_latest_signal(data)     # 最新一根的信号 dict
signal = gen.to_signal(data)             # core.signal.Signal 契约对象
```

输出列：`signal_buy` / `signal_sell`（互斥，两侧同时过阈值只保留分值高的一侧）、`signal_buy_score` / `signal_sell_score`、`signal_strength`，以及均线/MACD/KDJ/RSI/布林/量能/突破 7 个分项列。

信号契约（`core/signal.Signal`）：`{symbol, signal_date, action∈{BUY,HOLD,SELL}, strength, scale, reasons, confidence, executable, blocked_reasons, source, ...}`。`scale` 显式声明刻度，跨模块比较前必须核对。

### 3.2 DailySignalGenerator（`daily_signal_generator.py`）

外壳层：市场体制检测 + 按体制选参数 + 批量日报；内层打分委托 `SignalGenerator`。

```python
from daily_signal_generator import DailySignalGenerator
```

### 3.3 MultiFactorSelector（`multi_factor_selection.py`）

横截面多因子选股（回答"买什么"）。因子原始计算委托 `factor_library.py`（单一真相源），打分为横截面 z-score 加权。

```python
from multi_factor_selection import MultiFactorSelector

selector = MultiFactorSelector()
factors = selector.calculate_factors(financial_df, price_df)
selected = selector.select_stocks(
    financial_df, price_df, top_n=20, as_of="2026-06-30")
```

**point-in-time 约束**：`select_stocks` 要求财务数据含公告日列并显式传 `as_of`，经 `filter_point_in_time` 过滤——禁止用未来公告的财务数据选股。

其他：`FactorEffectivenessTester`（IC/IR 检验）、`PortfolioOptimizer`（Markowitz / 风险平价 / 最小方差）。

### 3.4 StockSelector（`stock_selector.py`）

单股绝对评分选股（0-100 分），权重与阈值外置 `config/stock_selector.json`。与 MFS 的 z-score 刻度不同，不合并。

### 3.5 其他

| 模块 | 职责 |
|------|------|
| `long_term_selector.py` | 基本面长期持仓候选 |
| `reversal_detector.py` + `reversal_rules.py` | 反转规则（实盘/回测共用同一规则实现） |
| `market_regime_classifier.py` | 市场状态分类（驱动参数切换，不产买卖信号） |
| `ml_predictor.py` | ML 涨跌预测（`MLPredictor` 分类 / `RegressionPredictor` 回归；`PredictionResult.to_signal()` 转信号契约） |

---

## 4. 回测与优化层

### 4.1 BacktestEngine（引擎 A，`backtest_framework.py`）

逐笔事件驱动回测。

```python
from backtest_framework import (BacktestEngine, PositionConfig,
                                PositionSizingMethod, StopLossMethod)

engine = BacktestEngine(initial_cash=1_000_000,
                        position_config=PositionConfig(
                            sizing_method=PositionSizingMethod.EQUAL_WEIGHT,
                            stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
                            stop_loss_pct=0.05))
result = engine.run(data, strategy=ma_cross_strategy, symbol="600519",
                    warmup_data=history_df)   # walk-forward 窗口预热
```

成交约束：t+1 成交、涨跌停限制、手续费/印花税（经 `execution_model` 统一）；买入量受 `PositionConfig.max_volume_participation`（当日成交额参与率）限制。

### 4.2 VectorizedBacktester（引擎 B，`vectorized_backtest.py`）

向量化回测，日频 mark-to-market 权益曲线。

```python
from vectorized_backtest import VectorizedBacktester

bt = VectorizedBacktester()
result = bt.backtest(data, params, history=history_df,
                     trading_calendar=calendar)   # 均可选
```

`min_holding_days` 默认 0（不锁退出）；持仓期间的新买讯忽略。

### 4.3 其他引擎

| 模块 | 说明 |
|------|------|
| `reversal_backtest.py` | 反转策略专用回测，复用 `reversal_rules` |
| `multi_stock_backtester.py` | 多股并行回测编排 |

### 4.4 OptimizationEngine（`optimization_engine.py`）

遗传算法参数优化，`seed=` 可复现。入口按优化模式区分：

```python
from optimization_engine import OptimizationEngine, FitnessConfig

engine = OptimizationEngine(seed=42)
engine.load_data(symbols=["600519", "000858"])
result = engine.optimize_global(n_stocks=50)      # 全局一套参数
# result = engine.optimize_by_regime(...)          # 按市场体制分参数
# result = engine.optimize_robust(...)             # 多体制稳健
# rounds  = engine.iterative_optimize(n_rounds=3)  # 迭代逐轮加严
```

关键口径：

- **适应度只由样本内（IS）窗口计算**；walk-forward 末尾 `oos_ratio` 比例的窗口留作样本外（OOS），指标只报告、从不参与参数选择（`split_is_oos`）。
- `confidence` = 适应度的 [0,1] 夹取（`confidence_from_fitness`），不是统计校准概率。
- 逐股回测失败会被记账并按比例惩罚适应度；成功率低于 `min_success_rate` 时参数组作废。
- 稳健性证据（试验次数、bootstrap）在 GA 结束后组装，只报告不扰动搜索。

配置驱动：`OptimizationEngine(config=)` / CLI `run --config x.json`，参数空间定义在 `parameter_space.py`，结果落盘 `best_params.json`（含参数空间指纹）供信号层下发。

### 4.5 HistoricalBacktestValidator（`historical_backtest_validator.py`）

历史验证链：用历史数据检验"参数拟合区间之后"的真实表现。**本模块不做回测**——只做验证编排与样本外隔离检查，回测本身委托上述引擎。

### 4.6 策略优化器（`strategy_optimizer.py`）

独立的策略模板参数搜索（网格 / 随机 / 边界采样），与 GA 引擎互补：

```python
from strategy_optimizer import StrategyOptimizer, MAStrategy
result = StrategyOptimizer(strategy=MAStrategy()).grid_search(
    data, param_grid={"short_period": [5, 10], "long_period": [20, 60]})
```

---

## 5. 执行与风控层

| 模块 | 职责 |
|------|------|
| `execution_model.py` | t+1 成交、涨跌停限制、费用模型（四回测引擎共用）；停牌日无行情日历则不虚构成交 |
| `trade_constraints.py` | 下单前约束检查（停牌/数据过期/涨跌停），输出 `ConstraintReport` |
| `portfolio_manager.py` | 组合持仓、集中度/现金闸门、再平衡、绩效报告 |
| `risk_management.py` | `StopLossManager` / `PortfolioRiskMonitor` |
| `position_analyzer.py` | 单股持仓分析（盈亏、技术状态、MACD 交叉判定、t+1 提示） |
| `core/trading_calendar.py` | 交易日历（由指数行情反推）与停牌识别 |
| `core/signal.py` / `core/fetch_result.py` | 信号契约 / 取数结果契约 |

---

## 6. Web 应用

```bash
python run_web_app.py        # 或 streamlit run .claude/skills/web_app.py
```

页面：仪表盘、数据分析（K 线/指标/信号）、策略回测、组合管理、实时监控、历史验证。可选依赖缺失时如实降级（核心 import 不依赖 streamlit）。

---

## 附录：数据格式

行情 DataFrame（标准列名）：

```
日期(datetime) 开盘 最高 最低 收盘 成交量 成交额 涨跌幅
```

信号契约 `Signal` 与选股契约 `Selection` 的完整字段定义见 `core/signal.py`。

复权落库：`{symbol}.parquet`（不复权）/ `{symbol}_qfq.parquet` / `{symbol}_hfq.parquet`，元数据记录口径。
