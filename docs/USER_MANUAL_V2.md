# 用户手册

从命令行/Web 两个角度说明各功能模块的用法。安装与部署见 [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md)，API 签名详见 [API_REFERENCE.md](../API_REFERENCE.md)。

所有代码示例**从仓库根目录运行**。

## 快速开始

```bash
pip install -r .claude/skills/requirements.txt    # 分析层
pip install -r web_requirements.txt               # Web（可选）

python run_web_app.py                             # http://localhost:8501
```

---

## 功能指南

### 1. 数据获取

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()

# 单只（默认后复权，本地缓存优先）
data = fetcher.get_quote_data("600519", days=120)

# 多只批量
all_data = fetcher.batch_get_quotes(
    ["600519", "000858", "002415"], days=120)

# 需要结构化结果（含错误信息）时用 FetchResult
result = fetcher.get_quote_result("600519", days=120)
if result.ok:
    df = result.data
else:
    print(result.error)
```

数据格式（标准列名，映射定义在 `core/dataframe.py`）：

```
日期(datetime) | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 成交额 | 涨跌幅
```

复权口径：`adjust="hfq"`（默认，后复权）/ `"qfq"` / `""`（不复权）。需要真实成交价的场景（如持仓成本对比）显式传 `adjust=""`。

### 2. 技术分析

```python
data = fetcher.calculate_technical_indicators(data)
# 追加 MA5/10/20/60, EMA20/50, MACD, RSI, K/D/J, 布林带, ATR 等列
print(data[["日期", "收盘", "MA5", "MA20", "RSI", "MACD"]].tail())
```

指标公式单一真相源在 `core/indicators.py`；口径（Cutler RSI、Wilder ATR、递归 EMA 等）见 [skills_layers.md](skills_layers.md)。

### 3. 交易信号

```python
from signal_generator import SignalGenerator

generator = SignalGenerator()
data_with_signals = generator.generate_signals(data)
signal = generator.get_latest_signal(data)

print(signal["buy_signal"], signal["sell_signal"], signal["strength"])
print(generator.format_signal_report(signal))
```

| 列 | 说明 | 取值 |
|----|------|------|
| signal_ma_cross 等 7 列 | 分项信号 | -1~1 |
| signal_buy / signal_sell | 综合信号（互斥） | 0/1 |
| signal_buy_score / signal_sell_score | 买卖分值 | 数值 |
| signal_strength | 信号强度 | -10~10 |

### 4. 策略回测

```python
from backtest_framework import BacktestEngine, PositionConfig

engine = BacktestEngine(
    initial_cash=1_000_000,
    position_config=PositionConfig(max_positions=5, position_size_pct=0.2))

result = engine.run(data, strategy=lambda d: 1 if d.iloc[-1].get("signal_buy") else 0)

print(f"总收益率: {result['total_return']:.2f}%")
print(f"夏普比率: {result['sharpe_ratio']:.2f}")
print(f"最大回撤: {result['max_drawdown']:.2f}%")
```

`run` 返回 dict。持仓/止损配置：

```python
from backtest_framework import PositionSizingMethod, StopLossMethod

PositionConfig(
    sizing_method=PositionSizingMethod.EQUAL_WEIGHT,
    stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
    stop_loss_pct=0.05,
    take_profit_pct=0.15,
    max_positions=10,
    position_size_pct=0.1,
)
```

### 5. 组合管理

```python
from portfolio_manager import PortfolioManager

manager = PortfolioManager()
pid = manager.create_portfolio(name="我的策略", cash=1_000_000)
manager.add_position(portfolio_id=pid, symbol="600519", shares=100, price=1800)

manager.rebalance(portfolio_id=pid,
                  target_weights={"600519": 0.3, "000858": 0.3, "002415": 0.4})

performance = manager.get_performance(pid)
risk = manager.get_risk_metrics(pid)
```

### 6. 实时监控

```python
from real_time_monitor import (RealTimeMonitor, AlertCondition,
                               AlertType, AlertPriority)

monitor = RealTimeMonitor()
monitor.add_stock("600519", "贵州茅台")
monitor.add_condition("600519", AlertCondition(
    alert_type=AlertType.PRICE_ABOVE, threshold=2000,
    priority=AlertPriority.HIGH))

for alert in monitor.check_conditions("600519"):
    print(alert.message)
```

告警类型：`PRICE_ABOVE` / `PRICE_BELOW` / `CHANGE_UP` / `CHANGE_DOWN` /
`BREAKOUT_HIGH` / `BREAKOUT_LOW` / `SIGNAL_BUY` / `SIGNAL_SELL` / `VOLUME_SURGE`。

### 7. 数据可视化

```python
from chart_visualizer import ChartVisualizer

visualizer = ChartVisualizer(output_dir="charts")
visualizer.plot_candlestick(data, symbol="600519", ma_periods=[5, 10, 20, 60])
visualizer.plot_macd(data, "600519")
visualizer.plot_rsi(data, "600519")
visualizer.plot_bollinger_bands(data, "600519")
visualizer.plot_combined_analysis(data, "600519")
```

### 8. 机器学习预测

```python
from ml_predictor import MLPredictor

predictor = MLPredictor(model_type="random_forest")
evaluation = predictor.train(data, test_size=0.2, forward_days=5, threshold=0.02)
print(f"准确率: {evaluation.accuracy:.2%}")

result = predictor.predict(data)
print(result.prediction, result.probability)
```

### 9. 策略参数优化

```python
from strategy_optimizer import StrategyOptimizer, MAStrategy

optimizer = StrategyOptimizer(strategy=MAStrategy())
result = optimizer.grid_search(data, param_grid={
    "short_period": [5, 10, 15],
    "long_period": [20, 30, 40]})
print(result.parameters, result.score)
```

需要样本内/样本外隔离的遗传算法优化用 `optimization_engine`（见 [API_REFERENCE.md](../API_REFERENCE.md) §4.4）。

---

## 常见场景

### 批量选股

```python
symbols = ["600519", "000858", "002415", "600036", "000001"]
all_data = fetcher.batch_get_quotes(symbols, days=252)

from signal_generator import SignalGenerator
generator = SignalGenerator()

buy_stocks = []
for symbol, df in all_data.items():
    sig = generator.get_latest_signal(df)
    if sig["buy_signal"]:
        buy_stocks.append((symbol, sig["strength"]))

buy_stocks.sort(key=lambda x: x[1], reverse=True)
```

### 回测一个自定义策略

```python
def ma_strategy(d):
    """返回 1/-1/0 表示买/卖/持有。"""
    ma5 = d["收盘"].rolling(5).mean()
    ma20 = d["收盘"].rolling(20).mean()
    if ma5.iloc[-1] > ma20.iloc[-1] and ma5.iloc[-2] <= ma20.iloc[-2]:
        return 1
    if ma5.iloc[-1] < ma20.iloc[-1] and ma5.iloc[-2] >= ma20.iloc[-2]:
        return -1
    return 0

engine = BacktestEngine(initial_cash=1_000_000)
result = engine.run(data, strategy=ma_strategy)
```

### 实时监控 + 回调

```python
import time

def notify(alert):
    print(f"告警: {alert.message}")

monitor.register_callback(notify)

while True:
    monitor.check_conditions("600519")
    time.sleep(3600)
```

---

## 最佳实践

1. **错误处理**：关键取数用 `get_quote_result`（FetchResult 契约），失败时 `ok=False` + `error`，不要依赖空 DataFrame 判断失败。
2. **批量操作**：`batch_get_quotes` 内置缓存与限速；更大规模用 `historical_data_manager.py batch` CLI 预取。
3. **数据新鲜度**：信号对数据末日敏感；"数据过期"检查按交易日计（`trade_constraints`）。
4. **复权一致性**：同一分析内不要混用复权口径；回测/信号用默认 hfq，与实时报价对比用 `adjust=""`。
