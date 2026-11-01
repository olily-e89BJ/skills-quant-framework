# 快速入门指南

从安装到跑通"取数 → 信号 → 回测"全流程约 5 分钟。所有脚本**从仓库根目录运行**。

## 安装

```bash
pip install -r .claude/skills/requirements.txt    # 分析层（必需）
pip install -r web_requirements.txt               # Web 界面（可选）
```

Python 3.11+ 推荐（CI 覆盖 3.11/3.12）。

## 五分钟上手

### 1. 取数并计算技术指标

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()
data = fetcher.get_quote_data("600519", days=252)   # 默认后复权
data = fetcher.calculate_technical_indicators(data)
print(data[["日期", "收盘", "MA5", "MA20", "MACD", "RSI"]].tail())
```

数据优先读本地缓存（`stock_data/`），缺失时联网回补并落盘。复权口径说明见 [API_REFERENCE.md](API_REFERENCE.md) 第 1 节。

### 2. 生成交易信号

```python
from signal_generator import SignalGenerator

generator = SignalGenerator()
signal = generator.get_latest_signal(data)
print(generator.format_signal_report(signal))
```

`get_latest_signal` 返回 dict：`buy_signal` / `sell_signal`（互斥）、`strength`（-10~10）、7 个分项信号、`executable`（可执行性检查结果）。信号报告会按分项给出文字解读（金叉/超卖等）。

### 3. 绘制 K 线图

```python
from chart_visualizer import ChartVisualizer

visualizer = ChartVisualizer()
visualizer.plot_candlestick(data, symbol="600519", save_path="charts/600519.png")
```

其他图型：`plot_macd` / `plot_rsi` / `plot_bollinger_bands` / `plot_equity_curve` / `plot_drawdown` / `plot_signals` / `plot_combined_analysis`。

### 4. 回测

```python
from backtest_framework import BacktestEngine

engine = BacktestEngine(initial_cash=1_000_000)
result = engine.run(data, strategy=lambda d: 1 if d.iloc[-1].get("signal_buy") else 0)

print(f"总收益率: {result['total_return']:.2f}%")
print(f"最大回撤: {result['max_drawdown']:.2f}%")
print(f"夏普比率: {result['sharpe_ratio']:.2f}")
```

`run(data, strategy)` 的 `strategy` 是一个函数，接收截至当前 bar 的 DataFrame，返回 1（买）/ -1（卖）/ 0（持有）。回测遵守 t+1 成交、涨跌停限制与费用模型。

内置策略模板可直接用：`from backtest_framework import ma_cross_strategy, macd_strategy, rsi_strategy`。

## 核心概念

### 数据格式

所有模块使用统一列名的 DataFrame（映射定义在 `core/dataframe.py`）：

```
日期(datetime) | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 成交额 | 涨跌幅
```

### 信号列

`generate_signals(data)` 会在 DataFrame 上追加：

| 列 | 含义 |
|----|------|
| `signal_buy` / `signal_sell` | 综合买入/卖出信号（互斥） |
| `signal_buy_score` / `signal_sell_score` | 买卖分值 |
| `signal_strength` | 信号强度（-10 到 10） |
| `signal_ma_cross` 等 7 列 | 各分项信号 |

### 配置对象

```python
from backtest_framework import PositionConfig, PositionSizingMethod, StopLossMethod

PositionConfig(
    sizing_method=PositionSizingMethod.EQUAL_WEIGHT,
    stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
    stop_loss_pct=0.05,
    max_positions=5,
    position_size_pct=0.2,
)
```

## 常见场景

### 批量筛选

```python
stocks = ["600519", "000858", "002415", "600036", "601318"]
all_data = fetcher.batch_get_quotes(stocks, days=252)

hits = []
for symbol, df in all_data.items():
    if len(df) == 0:
        continue
    sig = generator.get_latest_signal(df)
    if sig["buy_signal"] and sig["strength"] > 5:
        hits.append((symbol, sig["strength"]))

hits.sort(key=lambda x: x[1], reverse=True)
for symbol, strength in hits:
    print(f"{symbol}: 强度 {strength:+.1f}")
```

### 实时监控

```python
from real_time_monitor import RealTimeMonitor, AlertCondition, AlertType, AlertPriority

monitor = RealTimeMonitor()
monitor.add_stock("600519", "贵州茅台")
monitor.add_condition("600519", AlertCondition(
    alert_type=AlertType.PRICE_ABOVE, threshold=2000,
    priority=AlertPriority.HIGH))

for alert in monitor.check_conditions("600519"):
    print(alert.message)
```

### 策略参数搜索

```python
from strategy_optimizer import StrategyOptimizer, MAStrategy

optimizer = StrategyOptimizer(strategy=MAStrategy())
result = optimizer.grid_search(data, param_grid={
    "short_period": [5, 10, 15],
    "long_period": [20, 30, 40],
})
print(result.parameters, result.score)
```

更完整的遗传算法优化（含样本内/样本外隔离）见 `optimization_engine`，用法见 [API_REFERENCE.md](API_REFERENCE.md) 第 4.4 节。

## 下一步

- [API_REFERENCE.md](API_REFERENCE.md) — 完整 API 与口径说明
- [docs/USAGE_EXAMPLES.md](docs/USAGE_EXAMPLES.md) — 更多代码示例
- [docs/skills_layers.md](docs/skills_layers.md) — 分层架构与契约
- [docs/FAQ.md](docs/FAQ.md) — 常见问题
