# -*- coding: utf-8 -*-
"""params → 指标单一真相源 (主流程阶段 2 接线)

背景: 同一 params → 周期的映射曾写三遍 (S2 `daily_signal_generator` /
引擎 B `vectorized_backtest` / 主流程 `stock_data_fetcher`) —— 公式层已统一
在 `core/indicators.py`, 映射层未统一, 新增参数维必漏改一处。
本模块收敛**主流程侧**的映射 (S2 亦委托此处, 引擎 B 小写列名契约不动,
见 plan §5.2.1 P6 决策: 收敛 = 公式同源 + 列名桥接, 非列名归一)。

口径:
- 输出 **S2 大写风格**列: `MA_Fast/MA_Mid/MA_Slow` + `MACD*` + `RSI` +
  `K/D/J` + `BB_*` + `TR/ATR` + `Vol_MA*`
- **保留出厂锚点** `MA5/MA10/MA20/MA60` (+`EMA20/EMA50`): 选股层/技术评分
  按 5/10/20 网格标定 (R4), 不随 params 漂移
- 公式全部走 `IndicatorEngine` (core 单一真相源); 本模块只做参数→周期映射,
  不得出现裸 `.ewm(...)` / `.rolling(...).mean()` 指标公式
- `PARAMS_COLUMN_MAP` = S1 契约列名 → params 周期列 (与 S2 现用映射同值,
  `daily_signal_generator.generate_signal`), 供 `SignalGenerator(column_map=)`
  桥接 —— 信号层读契约列名, 实际吃到 params 周期列

用法::

    from indicator_params import (PARAMS_COLUMN_MAP, compute_params_indicators,
                                  resolve_params)
    frame = compute_params_indicators(raw_df, params)   # 阶段 2
    gen = generator_from_params(params, column_map=PARAMS_COLUMN_MAP)  # 阶段 4
"""
import pandas as pd

from core.indicator_engine import IndicatorEngine
from parameter_space import ParameterSpace

# S1 契约列名 → params 周期列 (桥接信号层; 与 S2 现用映射同值)
PARAMS_COLUMN_MAP = {'MA5': 'MA_Fast', 'MA10': 'MA_Mid', 'MA20': 'MA_Slow'}

# 出厂锚点周期 (不随 params — 选股层/技术评分按此网格标定, R4 边界)
ANCHOR_MA_PERIODS = (5, 10, 20, 60)


def resolve_params(params=None) -> dict:
    """26 维合并: `ParameterSpace.get_defaults()` + 调用方覆盖。

    None → 纯出厂默认; dict → 出厂默认逐键覆盖 (未知键原样保留,
    与 `optimized_params.load_optimized_params` 软校验口径一致)。
    """
    out = ParameterSpace.get_defaults()
    if params:
        out.update(params)
    return out


def compute_params_indicators(df: pd.DataFrame, params=None) -> pd.DataFrame:
    """按 params 周期计算指标列 (原地修改并返回)。

    Parameters
    ----------
    df : 含 收盘/最高/最低/成交量 的 DataFrame
    params : 优化器下发参数字典 (可选; None → 出厂默认周期)

    Returns
    -------
    pd.DataFrame
        params 周期列 (S2 大写风格) + 出厂锚点列 (MA5/10/20/60 等)。
        与 S2 `daily_signal_generator.compute_indicators` 同 params →
        同周期 → 同 engine 调用, 数值逐位同源。
    """
    if df.empty or '收盘' not in df.columns:
        return df

    p = resolve_params(params)
    eng = IndicatorEngine(df)

    # ---- 出厂锚点 (R4: 选股/技术评分标定网格, 不随 params) ----
    for period in ANCHOR_MA_PERIODS:
        df[f'MA{period}'] = eng.ma(period)
    df['EMA20'] = eng.ema(20)
    df['EMA50'] = eng.ema(50)

    # ---- params 周期列 (S2 大写风格 — 信号层经 PARAMS_COLUMN_MAP 消费) ----
    df['MA_Fast'] = eng.ma(int(p['ma_fast']))
    df['MA_Mid'] = eng.ma(int(p['ma_mid']))
    df['MA_Slow'] = eng.ma(int(p['ma_slow']))

    dif, dea, hist = eng.macd(int(p['macd_fast']), int(p['macd_slow']),
                              int(p['macd_signal']))
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = dif, dea, hist

    df['RSI'] = eng.rsi(int(p['rsi_period']))

    k, d, j = eng.kdj(int(p['kdj_n']))
    df['K'], df['D'], df['J'] = k, d, j

    upper, middle, lower, std = eng.bollinger(int(p['bb_period']),
                                              float(p['bb_std']))
    df['BB_Middle'], df['BB_Std'] = middle, std
    df['BB_Upper'], df['BB_Lower'] = upper, lower

    df['TR'] = eng.true_range()
    df['ATR'] = eng.atr(int(p['atr_period']))

    # ---- 量均线 (参数空间无周期维; S2 命名 + 出厂别名) ----
    df['Vol_MA5'] = eng.volume_ma(5)
    df['Vol_MA20'] = eng.volume_ma(20)
    df['VOL_MA5'] = df['Vol_MA5']

    return df
