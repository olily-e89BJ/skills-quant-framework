# 量化分析流程指南

本框架的分析流程分七个阶段。各阶段职责边界与模块对应关系见 `docs/skills_layers.md`。

```
数据获取 → 指标计算 → 形态识别 → 综合评分 → 风险评估 → 回测验证 → 仓位建议
```

编排入口是 `quant_workflow.QuantWorkflow`（提供 `quick_analysis` / `full_analysis` / `screen_stocks` / `batch_analysis` 等方法），也可按阶段单独调用下方模块。

## 各阶段说明

### 阶段 1：数据获取与清洗

**目标**：获取标准化的历史行情数据。

- 入口：`stock_data_fetcher.StockDataFetcher.get_quote_data(symbol, days, adjust)`（默认后复权，本地缓存优先）
- 列名标准化与涨跌幅派生：`core/dataframe.py`（单一真相源）
- 缓存落盘：`historical_data_manager`（Parquet，复权口径入库）
- 批量：`batch_get_quotes(symbols, days)`

**输出**：标准列名 DataFrame（`日期/开盘/最高/最低/收盘/成交量/成交额/涨跌幅`）。

### 阶段 2：技术指标计算

**目标**：计算技术指标列。

| 类别 | 指标 | 实现位置 |
|------|------|----------|
| 趋势 | MA / EMA / MACD | `core/indicators.py`（公式真相源） |
| 动量 | RSI（Cutler 口径） | 同上 |
| 震荡 | KDJ | 同上 |
| 波动 | BOLL / ATR（Wilder RMA） | 同上 |
| 成交量 | 量均线 / OBV / VWAP（累积口径） | 同上 |
| 高级 | HMA, KAMA, CCI, MFI, Ichimoku 等 | `advanced_indicators.py` / `trend_indicators.py` |

快速批量计算用 `fetcher.calculate_technical_indicators(df)` 或 `IndicatorEngine`。

### 阶段 3：形态识别

**目标**：识别 K 线形态与价格形态。

- K 线形态：锤子线、上吊线、吞没、孕线、晨星/暮星、三兵/三鸦等（`pattern_recognition.py`，布尔列输出）
- 支撑/压力、趋势判断：`technical_analyzer.TechnicalAnalyzer.analyze(symbol, days)`

### 阶段 4：综合评分与选股

**目标**：多维度评分排序。

两条独立的评分路线（刻度不同，不混用）：

1. **单股绝对评分（0-100）**：`stock_selector`，维度含趋势/动量/超买超卖/量能/形态，阈值外置 `config/stock_selector.json`。
2. **横截面相对排序（z-score）**：`multi_factor_selection.MultiFactorSelector.select_stocks(financial_df, top_n, as_of)`，因子权重外置 `config/multi_factor.json`，强制 point-in-time 公告日过滤。

### 阶段 5：风险评估

**目标**：量化风险水平。

| 指标 | 公式 | 口径 |
|------|------|------|
| 年化波动率 | std(returns) × √252 | — |
| 最大回撤 | 峰谷跌幅 | `core/metrics.max_drawdown_pct`，正值% |
| 夏普比率 | (return − rf) / volatility | `core/metrics.sharpe_ratio`，rf=0.03，ddof=1 |
| 盈亏比 | Σ盈利 / \|Σ亏损\| | `core/metrics.profit_factor` |
| 胜率 | 盈利笔数 / 全部笔数 | `core/metrics.win_rate`，持平计分母不算赢 |

模块：`risk_management.py`（`RiskMetrics` / `StopLossManager` / `PortfolioRiskMonitor`）。

### 阶段 6：回测验证

**目标**：验证策略历史表现。

1. 定义信号（`signal_generator.generate_signals` 或自定义策略函数）
2. 运行回测（引擎 A `backtest_framework.BacktestEngine.run` / 引擎 B `vectorized_backtest`）
3. 查看绩效（总收益/年化/夏普/回撤/胜率/交易次数，经 `core/metrics` 统一口径）

内置策略模板：MA 交叉、MACD 交叉、RSI 超买超卖、布林带、多信号组合（`StrategyFactory`）。

回测遵守 t+1 成交、涨跌停限制、手续费/印花税与成交容量约束（`execution_model`）。

### 阶段 7：仓位管理

**目标**：确定买入仓位与风控规则。

仓位计算方法（`risk_management.PositionSizing`）：

1. **固定比例法**：仓位 = 本金 × 风险比例 / 止损幅度
2. **凯利公式**：f = (胜率 × 平均盈利 − 平均亏损) / 平均盈利
3. **ATR 波动法**：股数 = 本金 × 风险比例 / ATR

持仓约束经 `portfolio_manager` 执行（集中度上限、现金闸门）。

## 快速开始

### 完整分析

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow(initial_capital=100_000)
results = workflow.full_analysis(
    stocks={"600036": "招商银行", "000858": "五粮液", "600519": "贵州茅台"},
    days=252)
```

### 单股分析

```python
from quant_workflow import quick_analyze

result = quick_analyze("600519", days=252)
```

### 选股

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow()
picks = workflow.screen_stocks(top_n=10)
```

## 注意事项

1. 所有脚本从仓库根目录运行（裸模块名导入依赖相对路径）。
2. 建议至少 200 个交易日历史数据，指标预热不足时信号前段为 NaN。
3. 停牌识别需要本地指数行情（`historical_data_manager fetch --index 000001`），无指数数据时停牌检查如实跳过。
4. 技术分析仅供参考，不构成投资建议；历史表现不代表未来收益。
