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

**优化参数下发（26 维指标周期维）**：`calculate_technical_indicators(df, params)` 在给定优化器参数时改走 `indicator_params.compute_params_indicators` —— 周期随 `params` 真变（`MA_Fast/MA_Mid/MA_Slow`、`MACD*`、`RSI`、`K/D/J`、`BB_*`、`ATR` 等 S2 大写风格列，信号层经 `indicator_params.PARAMS_COLUMN_MAP` 桥接消费），同时并存**出厂锚点列**（`MA5/MA10/MA20/MA60`、`EMA20/50` —— 选股与技术评分层保持出厂标定，不随 params，口径边界见 plan §5.3）。不传 `params` → 出厂周期逐位不变（零回归）。公式仍全部经 `IndicatorEngine` → `core/indicators.py`。

快速分析编排经 `QuantWorkflow(params=...)` / `quick_analyze(symbol, params=...)` / `full_analyze(..., params=...)` 贯通阶段 2/4。

### 阶段 3：形态识别

**目标**：识别 K 线形态与价格形态。

- K 线形态：锤子线、上吊线、吞没、孕线、晨星/暮星、三兵/三鸦等（`pattern_recognition.py`，布尔列输出）
- 支撑/压力、趋势判断：`technical_analyzer.TechnicalAnalyzer.analyze(symbol, days)`

### 阶段 4：综合评分与选股

**目标**：多维度评分排序。

两条独立的评分路线（刻度不同，不混用）：

1. **单股绝对评分（0-100）**：`stock_selector`，维度含趋势/动量/超买超卖/量能/形态，阈值外置 `config/stock_selector.json`。
2. **横截面相对排序（z-score）**：`multi_factor_selection.MultiFactorSelector.select_stocks(financial_df, top_n, as_of)`，因子权重外置 `config/multi_factor.json`，强制 point-in-time 公告日过滤。

**口径边界（R4）**：两条评分路线与 `technical_analyzer` 保持**出厂标定**，不接优化器 params（优化周期维只驱动择时链路：指标 → 信号 → 回测/实盘建议）。

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

1. 定义信号（`signal_generator.generate_signals` 或自定义策略函数）—— 加载优化参数时经 `generator_from_params(params, column_map=PARAMS_COLUMN_MAP)` 构造：信号层消费的是 **params 周期列**（`MA_Fast` 等），与指标层同 params 同源；显式映射列缺失会**抛错**（R5，不静默降级）。投票制分项公式与引擎 B 结构性不等价（带趋势确认 ±0.5 档位）、加权制冲突仲裁不同 —— 回测与实盘两侧各自逐位自洽，不作跨引擎信号逐位断言（plan §3.8）
2. 运行回测（引擎 A `backtest_framework.BacktestEngine.run` / 引擎 B `vectorized_backtest`）—— 仓位维（止损/止盈/追踪止损/仓位比例）经 `backtest_framework.position_config_from_params(params)` 落到引擎 A `PositionConfig`（显式 `sizing_value=` 覆盖优先，如 web 单只仓位滑杆）；引擎 B 直接消费 params 同名键
3. 查看绩效（总收益/年化/夏普/回撤/胜率/交易次数，经 `core/metrics` 统一口径）

内置策略模板：MA 交叉、MACD 交叉、RSI 超买超卖、布林带、多信号组合（`StrategyFactory`）。

回测遵守 t+1 成交、涨跌停限制、手续费/印花税与成交容量约束（`execution_model`）。

> **已知缺口（plan §8.1）**：引擎 A **无** `min_holding_days` 出场闸门 —— `position_config_from_params` 不消费该键（不新造闸门，只文档化）；引擎 B 经 params 直接消费。最短持有天数语义目前仅引擎 B 生效。

### 阶段 7：仓位管理

**目标**：确定买入仓位与风控规则。

仓位计算方法（`risk_management.PositionSizing`）：

1. **固定比例法**：仓位 = 本金 × 风险比例 / 止损幅度
2. **凯利公式**：f = (胜率 × 平均盈利 − 平均亏损) / 平均盈利
3. **ATR 波动法**：股数 = 本金 × 风险比例 / ATR

**优化参数下发（仓位维）**：`quant_workflow.QuantWorkflow.position_advice(symbol, capital)`（便捷入口 `position_advice(..., params=)`）按 params 输出止损三元组（`stop_loss_pct/take_profit_pct/trailing_stop_pct`）+ `position_size_pct`，建议仓位金额 = **min(固定比例风险预算, position_size_pct × capital)**（与引擎 B 同口径取小），另附 ATR 法参考股数（ATR 列随 params 周期）。web 组合页「添加持仓」把止损三元组直接注册进 `StopLossManager`（勾选「止损三元组用优化参数」时）。

持仓约束经 `portfolio_manager` 执行（集中度上限、现金闸门）。

## 优化参数下发与体制自动选择

优化器 26 维参数（11 指标周期维 + 5 仓位维 + 信号/评分维）从结果 JSON 下发到主流程的入口：

```python
from optimized_params import load_optimized_params, resolve_regime_params

# 手动: 全局/指定体制体系
params = load_optimized_params('stock_data/optimization_result.json')          # 全局优先
params = load_optimized_params('stock_data/optimization_result.json', regime='BULL')

# 自动: 按当前大盘体制选体系, 判定失败/无专属体系 → 全局降级 (不阻断)
params, info = resolve_regime_params('stock_data/optimization_result.json',
                                     regime='auto', with_info=True)
# info: {'regime_requested', 'regime_used', 'system_name', 'fallback'}
```

- **体制判定**：`optimized_params.current_market_regime()` —— 离线读本地指数行情（`historical/index/`，不联网）→ `market_regime_classifier.classify` → 最后一根交易日标签（`BULL/BEAR/SIDEWAYS/CRASH/RECOVERY`）；无本地指数数据/过短/异常 → `None`（如实降级，不臆造体制）。
- **web 入口**：侧边栏「🎯 优化参数」下拉含「自动（当前体制，失败则全局）」与各体制/全局体系；加载后全站信号面换实例、指标层三处调用同步传 params、口径标注（模式 + MA 快/中/慢 + RSI 周期 + 体系名）显示在侧边栏。未加载 params 时回出厂投票制（零回归）。
- **指标同源**：主流程 `indicator_params.compute_params_indicators` 与引擎 B `_compute_indicators` 同 params → 同公式逐位相等（门禁 `tests/test_main_flow_params.py::TestGate4EngineBSameIndicators`）；信号层不作跨引擎逐位断言（公式结构性不等价，plan §3.8）。

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

# 带优化参数 (指标周期/信号阈值/仓位维随 params 生效)
from optimized_params import load_optimized_params
params = load_optimized_params("stock_data/optimization_result.json")
result = quick_analyze("600519", days=252, params=params)

# 阶段 7 仓位建议 (止损三元组 + min(风险预算, position_size_pct×capital))
from quant_workflow import position_advice
adv = position_advice("600519", capital=100_000, params=params)
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
