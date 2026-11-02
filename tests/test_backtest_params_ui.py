# -*- coding: utf-8 -*-
"""回测页「策略参数 = optimization_result.json 生效参数」门禁。

背景: 策略回测页的策略参数面板此前是写死的 UI 默认值 (MA 5/20 滑杆 +
静态文案「使用默认MACD参数 (12, 26, 9)」), 与 `optimization_result.json`
下发的体系参数无关 —— **显示 ≠ 生效**; 且「MACD」「自定义」两个策略选项
与「多因子」走同一条代码路径, 「最大持仓」滑杆无任何消费。

本文件锁三件事:
1. 生效参数解析口径 (指标维 / 信号维 / 仓位维各自取运行时对象)
2. 出厂口径零回归 (未加载优化参数时数值逐位不变)
3. 页面诚实性 (无死控件 / 死选项 / 死 import; 策略走真身)
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

_SKILLS = os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills')
_WEB_APP = os.path.join(_SKILLS, 'web_app.py')

# 出厂口径 (未加载优化参数) 的真值 —— 页面显示必须等于这些值
FACTORY_MA = (5, 10, 20)          # ma_fast / ma_mid / ma_slow
FACTORY_MACD = (12, 26, 9)        # macd_fast / macd_slow / macd_signal
FACTORY_SIGNAL = 2.0              # SignalGenerator() 投票 buy/sell 阈值
FACTORY_POSITION = (0.08, 0.20, 0.05)  # 止损 / 止盈 / 追踪 (PositionConfig)


def _src(name='web_app.py'):
    with open(os.path.join(_SKILLS, name), encoding='utf-8') as f:
        return f.read()


def _ohlcv(n=300, seed=3):
    """合成 OHLCV (确定性随机游走, 无网络/无缓存)。"""
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return pd.DataFrame({
        '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
        '开盘': close * 1.001, '最高': close * 1.02, '最低': close * 0.98,
        '收盘': close,
        '成交量': rng.integers(1e6, 5e6, n).astype(float),
    })


# =============================================================================
# 1. 生效参数解析口径
# =============================================================================

class TestEffectiveParams:
    """生效参数一律从运行时对象反推 (显示 = 实际消费)。"""

    def test_factory_indicator_params_match_factory_path(self):
        from optimized_params import effective_indicator_params
        got = effective_indicator_params(None)
        assert (got['ma_fast'], got['ma_mid'], got['ma_slow']) == FACTORY_MA
        assert (got['macd_fast'], got['macd_slow'],
                got['macd_signal']) == FACTORY_MACD
        assert got['rsi_period'] == 14
        assert got['rsi_oversold'] == 30 and got['rsi_overbought'] == 70
        assert got['kdj_n'] == 9
        assert got['bb_period'] == 20 and got['bb_std'] == 2.0
        assert got['atr_period'] == 14

    def test_loaded_params_override_indicator(self):
        from optimized_params import effective_indicator_params
        got = effective_indicator_params({'ma_fast': 25, 'ma_slow': 63,
                                          'macd_fast': 8, 'macd_signal': 15})
        assert got['ma_fast'] == 25 and got['ma_slow'] == 63
        assert got['macd_fast'] == 8 and got['macd_signal'] == 15
        # 未覆盖的键保持出厂
        assert got['ma_mid'] == FACTORY_MA[1]

    def test_signal_params_read_live_generator(self):
        """出厂投票阈值 2.0/2.0 —— 与规范默认 3.0/4.0 不同, 以运行对象为准。"""
        from optimized_params import effective_signal_params
        from signal_generator import SignalGenerator
        got = effective_signal_params(SignalGenerator())
        assert got['buy_threshold'] == FACTORY_SIGNAL
        assert got['sell_threshold'] == FACTORY_SIGNAL
        assert got['score_buy_threshold'] == 60.0
        assert got['score_sell_threshold'] == 35.0
        # 规范默认不是运行值 → 兜底路径被锁死
        from parameter_space import ParameterSpace
        defaults = ParameterSpace.get_defaults()
        assert defaults['buy_threshold'] != FACTORY_SIGNAL

    def test_signal_params_from_loaded_generator(self):
        from optimized_params import effective_signal_params
        from signal_generator import generator_from_params
        params = {'buy_threshold': 2.4967, 'sell_threshold': 4.7475,
                  'score_buy_threshold': 40.0, 'score_sell_threshold': 50.0,
                  'w_trend': 23.5, 'w_momentum': 30.3, 'w_risk': 21.4,
                  'w_performance': 24.8, 'use_weighted_scoring': True}
        got = effective_signal_params(generator_from_params(params))
        assert got['buy_threshold'] == pytest.approx(2.4967)
        assert got['sell_threshold'] == pytest.approx(4.7475)
        assert got['score_buy_threshold'] == 40.0
        assert got['w_trend'] == pytest.approx(23.5)

    def test_position_params_read_live_config(self):
        """出厂 PositionConfig 口径 (8%/20%/5%, 止盈未启用) —— 非规范默认。"""
        from backtest_framework import PositionConfig
        from optimized_params import effective_position_params
        got = effective_position_params(PositionConfig())
        assert got['stop_loss_pct'] == FACTORY_POSITION[0]
        assert got['take_profit_pct'] == FACTORY_POSITION[1]
        assert got['trailing_stop_pct'] == FACTORY_POSITION[2]
        assert got['take_profit_enabled'] is False
        assert got['position_size_pct'] == 0.95  # PositionConfig 字段默认
        from parameter_space import ParameterSpace
        defaults = ParameterSpace.get_defaults()
        assert defaults['stop_loss_pct'] != FACTORY_POSITION[0]

    def test_factory_defaults_expose_position_config_fields(self):
        from backtest_framework import PositionConfig
        got = PositionConfig.factory_defaults()
        assert got['stop_loss_pct'] == FACTORY_POSITION[0]
        assert got['take_profit_pct'] == FACTORY_POSITION[1]
        assert got['trailing_stop_pct'] == FACTORY_POSITION[2]
        assert got['take_profit_enabled'] is False

    def test_overview_rows_follow_parameter_space_order(self):
        from optimized_params import params_overview_rows
        from parameter_space import ParameterSpace
        rows = params_overview_rows({'ma_fast': 12})
        assert len(rows) == 26
        names = [r['参数'] for r in rows]
        assert names == [p.name for p in ParameterSpace.get_all_params()]
        assert rows[0]['组'] == '指标'

    def test_overview_rows_carry_notes(self):
        from optimized_params import params_overview_rows
        rows = params_overview_rows({'min_holding_days': 11},
                                    {'min_holding_days': '引擎 A 不消费'})
        hit = [r for r in rows if r['参数'] == 'min_holding_days']
        assert hit and hit[0]['备注'] == '引擎 A 不消费'

    def test_summary_mentions_key_dims(self):
        from optimized_params import format_effective_summary
        out = format_effective_summary(
            {'ma_fast': 12, 'ma_mid': 18, 'ma_slow': 21,
             'macd_fast': 8, 'macd_slow': 38, 'macd_signal': 15,
             'rsi_period': 25, 'stop_loss_pct': 0.03,
             'take_profit_pct': 0.1, 'trailing_stop_pct': 0.0676,
             'position_size_pct': 0.2},
            'stock_data/optimization_result.json · GLOBAL')
        assert 'MA 12/18/21' in out
        assert 'MACD 8/38/15' in out
        assert '止损3.0%' in out
        assert 'optimization_result.json' in out


# =============================================================================
# 2. 出厂口径零回归
# =============================================================================

class TestFactoryRegression:
    """未加载优化参数时, 页面行为与改动前逐位一致。"""

    def test_factory_position_config_keeps_take_profit_disabled(self):
        """出厂口径止盈**未启用** (打开它 = 悄悄改变历史回测口径)。"""
        from backtest_framework import PositionConfig
        from web_app import _build_position_config
        cfg = _build_position_config(None, 0.2, 0.08, 0.20, 0.05)
        assert cfg.take_profit_enabled is False
        assert cfg.stop_loss_pct == FACTORY_POSITION[0]
        assert cfg.take_profit_pct == FACTORY_POSITION[1]
        assert cfg.trailing_stop_pct == FACTORY_POSITION[2]
        assert cfg.sizing_value == 0.2
        assert cfg.max_position_pct == 0.5

    def test_loaded_position_config_enables_take_profit(self):
        from web_app import _build_position_config
        params = {'stop_loss_pct': 0.03, 'take_profit_pct': 0.1,
                  'trailing_stop_pct': 0.0676, 'position_size_pct': 0.744}
        cfg = _build_position_config(params, 0.2, 0.03, 0.1, 0.0676)
        assert cfg.take_profit_enabled is True
        assert cfg.stop_loss_pct == 0.03
        # 单只仓位 = min(滑杆, 优化仓位比例) (不超优化口径)
        assert cfg.sizing_value == pytest.approx(0.2)

    def test_loaded_position_config_clamps_sizing_to_params(self):
        from web_app import _build_position_config
        params = {'position_size_pct': 0.3}
        cfg = _build_position_config(params, 0.9, 0.08, 0.2, 0.05)
        assert cfg.sizing_value == pytest.approx(0.3)

    def test_ma_strategy_equivalent_to_legacy_page_logic(self):
        """旧页面口径 (预计算 signal 列) vs StrategyFactory.ma_cross →
        逐位相同 (换实现不改数值)。"""
        from backtest_framework import BacktestEngine, PositionConfig, \
            StrategyFactory
        from core.indicators import sma as core_sma

        def legacy(df, short, long):
            df[f'MA{short}'] = core_sma(df['收盘'], short)
            df[f'MA{long}'] = core_sma(df['收盘'], long)
            df['signal_buy'] = (
                (df[f'MA{short}'] > df[f'MA{long}']) &
                (df[f'MA{short}'].shift(1) <= df[f'MA{long}'].shift(1)))
            df['signal_sell'] = (
                (df[f'MA{short}'] < df[f'MA{long}']) &
                (df[f'MA{short}'].shift(1) >= df[f'MA{long}'].shift(1)))

            def strat(d):
                if len(d) < 2:
                    return 0
                latest = d.iloc[-1]
                if latest.get('signal_buy', 0) == 1:
                    return 1
                elif latest.get('signal_sell', 0) == 1:
                    return -1
                return 0
            return strat

        cfg = lambda: PositionConfig(sizing_value=0.2, max_position_pct=0.5)
        for short, long in [(5, 20), (12, 21)]:
            d_old, d_new = _ohlcv(), _ohlcv()
            r_old = BacktestEngine(initial_cash=1_000_000,
                                   position_config=cfg()).run(
                d_old, legacy(d_old, short, long), symbol='X')
            r_new = BacktestEngine(initial_cash=1_000_000,
                                   position_config=cfg()).run(
                d_new, StrategyFactory.ma_cross(fast=short, slow=long),
                symbol='X')
            assert r_old['trade_count'] > 0, "合成数据应产生交易 (否则断言无意义)"
            assert r_old['trade_count'] == r_new['trade_count']
            assert r_old['total_return'] == pytest.approx(
                r_new['total_return'], rel=1e-12)

    def test_macd_strategy_is_distinct_from_multi_factor(self):
        """「MACD」不再与「多因子」同路 (此前两者都跑完整信号生成器)。"""
        from backtest_framework import BacktestEngine, PositionConfig, \
            StrategyFactory
        from core.indicator_engine import IndicatorEngine
        from signal_generator import SignalGenerator

        data = _ohlcv()
        eng = IndicatorEngine(data)
        dif, dea, hist = eng.macd(*FACTORY_MACD)
        data['MACD'], data['MACD_Signal'], data['MACD_Hist'] = dif, dea, hist
        data['RSI'] = eng.rsi(14)
        k, d, j = eng.kdj()
        data['K'], data['D'], data['J'] = k, d, j
        up, mid, lo, std = eng.bollinger(20, 2.0)
        data['BB_Middle'], data['BB_Std'] = mid, std
        data['BB_Upper'], data['BB_Lower'] = up, lo
        data['TR'] = eng.true_range()
        data['ATR'] = eng.atr(14)
        data['Vol_MA5'] = eng.volume_ma(5)
        data['VOL_MA5'] = data['Vol_MA5']
        for p in (5, 10, 20, 60):
            data[f'MA{p}'] = eng.ma(p)
        data['EMA20'] = eng.ema(20)
        data['EMA50'] = eng.ema(50)

        def sig_strat(d):
            if len(d) < 2:
                return 0
            latest = d.iloc[-1]
            if latest.get('signal_buy', 0) == 1:
                return 1
            elif latest.get('signal_sell', 0) == 1:
                return -1
            return 0

        cfg = lambda: PositionConfig(sizing_value=0.2, max_position_pct=0.5)
        r_multi = BacktestEngine(initial_cash=1_000_000,
                                 position_config=cfg()).run(
            SignalGenerator().generate_signals(data), sig_strat, symbol='X')
        r_macd = BacktestEngine(initial_cash=1_000_000,
                                position_config=cfg()).run(
            _ohlcv(), StrategyFactory.macd_cross(*FACTORY_MACD), symbol='X')
        assert r_multi['trade_count'] > 0 and r_macd['trade_count'] > 0
        assert (r_multi['trade_count'] != r_macd['trade_count']
                or r_multi['total_return'] != r_macd['total_return'])


# =============================================================================
# 3. 页面诚实性 (源码级)
# =============================================================================

class TestPageHonesty:
    """回测页不得再出现死控件 / 死选项 / 死 import / 静态假参数。"""

    def test_no_dead_controls(self):
        src = _src()
        assert '最大持仓' not in src, "「最大持仓」滑杆无消费 (引擎 A 单标的)"
        assert 'max_positions' not in src

    def test_no_dead_strategy_option(self):
        src = _src()
        assert '"自定义"' not in src, "「自定义」无独立行为 (与多因子同路)"

    def test_no_static_fake_params_text(self):
        src = _src()
        assert '使用默认MACD参数' not in src, \
            "MACD 参数应按生效值显示, 不是写死文案"
        assert '使用信号生成器的综合信号' not in src

    def test_no_hardcoded_slider_ranges(self):
        src = _src()
        assert 'st.slider("短期均线", 5, 20, 5)' not in src, \
            "滑杆量程须取参数空间规范 (装得下任意优化取值)"
        assert 'st.slider("长期均线", 20, 60, 20)' not in src

    def test_no_dead_import(self):
        src = _src()
        assert '_core_sma' not in src, \
            "MA 交叉已改用 StrategyFactory → _core_sma 成死 import"

    def test_strategies_wired_to_real_implementations(self):
        src = _src()
        assert 'StrategyFactory.ma_cross' in src
        assert 'StrategyFactory.macd_cross' in src
        assert 'position_config_from_params' in src

    def test_params_source_tracked(self):
        src = _src()
        assert 'optimized_params_source' in src
        assert 'params_overview_rows' in src
        assert 'format_effective_summary' in src

    def test_effective_params_drive_the_run(self):
        """面板值即回测消费值 (仓位配置与面板共用同一份)。"""
        src = _src()
        assert '_build_position_config(' in src
        assert 'position_config=position_config' in src


# =============================================================================
# 4. 页面渲染 (Streamlit AppTest, 需 streamlit)
# =============================================================================

def _app_test():
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(_WEB_APP, default_timeout=180)
    # 空自选 → 仪表盘不联网
    at.session_state['watchlist'] = []
    at.run()
    return at


def _params_payload():
    return {
        'use_weighted_scoring': True,
        'systems': [{
            'name': '测试体系型', 'regime': 'GLOBAL',
            'params': {
                'ma_fast': 25, 'ma_mid': 33, 'ma_slow': 63,
                'macd_fast': 9, 'macd_slow': 31, 'macd_signal': 13,
                'rsi_period': 21, 'rsi_oversold': 25.5, 'rsi_overbought': 75.5,
                'kdj_n': 11, 'bb_period': 26, 'bb_std': 1.5, 'atr_period': 19,
                'buy_threshold': 2.25, 'sell_threshold': 4.5,
                'score_buy_threshold': 42.0, 'score_sell_threshold': 47.0,
                'w_trend': 20.0, 'w_momentum': 30.0, 'w_risk': 25.0,
                'w_performance': 25.0,
                'stop_loss_pct': 0.05, 'take_profit_pct': 0.15,
                'trailing_stop_pct': 0.07, 'position_size_pct': 0.6,
                'min_holding_days': 12,
            },
        }],
    }


def _loaded_params():
    """下发口径: systems[].params + 顶层 use_weighted_scoring (同
    `optimized_params.load_optimized_params` 的产出形态)。"""
    payload = _params_payload()
    return {**payload['systems'][0]['params'],
            'use_weighted_scoring': payload['use_weighted_scoring']}


@pytest.mark.integration
class TestPageRender:
    """回测页渲染: 面板显示 = 生效参数 (无 streamlit 时整体跳过)。"""

    @staticmethod
    def _goto_backtest(at):
        at.radio[0].set_value("🔙 策略回测").run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at

    def test_factory_page_shows_factory_params(self):
        at = self._goto_backtest(_app_test())
        labels = {s.label: s.value for s in at.slider}
        assert labels['短期均线'] == FACTORY_MA[0]
        assert labels['长期均线'] == FACTORY_MA[2]
        nums = {n.label: n.value for n in at.number_input}
        assert nums['止损比例'] == FACTORY_POSITION[0]
        assert nums['止盈比例'] == FACTORY_POSITION[1]
        assert nums['追踪止损比例'] == FACTORY_POSITION[2]
        caps = ' '.join(c.value for c in at.caption)
        assert '出厂默认' in caps
        assert '出厂口径未启用' in caps

    def test_loaded_params_flow_into_panel(self):
        from signal_generator import generator_from_params
        from indicator_params import PARAMS_COLUMN_MAP

        params = _loaded_params()
        at = _app_test()
        at.session_state['optimized_params'] = params
        at.session_state['generator'] = generator_from_params(
            params, column_map=PARAMS_COLUMN_MAP)
        at.session_state['optimized_params_source'] = \
            'opt.json · GLOBAL · 测试体系型'
        self._goto_backtest(at)

        labels = {s.label: s.value for s in at.slider}
        assert labels['短期均线'] == 25
        assert labels['长期均线'] == 63
        nums = {n.label: n.value for n in at.number_input}
        assert nums['止损比例'] == 0.05
        assert nums['止盈比例'] == 0.15
        assert nums['追踪止损比例'] == 0.07
        caps = ' '.join(c.value for c in at.caption)
        assert 'opt.json · GLOBAL · 测试体系型' in caps
        assert '加权评分' in caps

    def test_loaded_params_detail_table_matches_json(self):
        from signal_generator import generator_from_params
        from indicator_params import PARAMS_COLUMN_MAP

        params = _loaded_params()
        at = _app_test()
        at.session_state['optimized_params'] = params
        at.session_state['generator'] = generator_from_params(
            params, column_map=PARAMS_COLUMN_MAP)
        self._goto_backtest(at)

        df = at.dataframe[0].value
        assert len(df) == 26
        rows = {r['参数']: r['生效值'] for _, r in df.iterrows()}
        assert rows['ma_fast'] == 25
        assert rows['ma_slow'] == 63
        assert rows['macd_fast'] == 9
        assert rows['stop_loss_pct'] == 0.05
        notes = {r['参数']: r['备注'] for _, r in df.iterrows()}
        assert '引擎 A 不消费' in notes['min_holding_days']

    def test_params_file_round_trip_from_disk(self):
        """optimization_result.json → load_optimized_params → 面板值。"""
        from optimized_params import load_optimized_params
        tmp = os.path.join(os.path.dirname(__file__), '_tmp_opt_params.json')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(_params_payload(), f)
            params = load_optimized_params(tmp)
            assert params['ma_fast'] == 25
            assert params['ma_slow'] == 63
            assert params['use_weighted_scoring'] is True
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_partial_params_fallback_follows_params_contract(self):
        """params 缺仓位维 → 兜底取 ParameterSpace 规范默认 (与
        `position_config_from_params` 同口径), **不是** PositionConfig 出厂值。"""
        from parameter_space import ParameterSpace
        from signal_generator import generator_from_params

        defaults = ParameterSpace.get_defaults()
        params = {'ma_fast': 12, 'ma_slow': 21,
                  'use_weighted_scoring': False}
        at = _app_test()
        at.session_state['optimized_params'] = params
        at.session_state['generator'] = generator_from_params(params)
        self._goto_backtest(at)

        nums = {n.label: n.value for n in at.number_input}
        assert nums['止损比例'] == defaults['stop_loss_pct']
        assert nums['止盈比例'] == defaults['take_profit_pct']
        assert nums['追踪止损比例'] == defaults['trailing_stop_pct']
        # 与出厂 PositionConfig 口径不同 (8%/20%/5%) —— 证明没混用
        from backtest_framework import PositionConfig
        fac = PositionConfig.factory_defaults()
        assert nums['止损比例'] != fac['stop_loss_pct']
