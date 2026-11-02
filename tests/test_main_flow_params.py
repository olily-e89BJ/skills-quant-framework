# -*- coding: utf-8 -*-
"""主流程优化参数接线门禁 (plan/optimized-params-main-flow-review §6, 7 组)。

口径边界 (plan §5.3): 选股层/技术评分层保持出厂标定 (R4), 不在本文件断言
扩展; 引擎 A 不新造 min_holding_days 闸门 (仅源码级断言缺口已文档化)。

门禁 #4 拆分 (plan P1): 指标层与引擎 B `_compute_indicators` 同 params →
逐位相等; **信号层不作逐位断言** — 投票制公式结构性不等价 (主流程带趋势
确认 ±0.5 档位)、加权制冲突仲裁不同 (plan §3.8)。
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from core.indicators import (atr as core_atr, bollinger as core_bollinger,
                             kdj as core_kdj, macd as core_macd,
                             rsi as core_rsi, sma as core_sma,
                             volume_ma as core_volume_ma)

_SKILLS = os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills')

REGIME_LABELS = {'BULL', 'BEAR', 'SIDEWAYS', 'CRASH', 'RECOVERY'}


def _ohlcv(n=150, seed=7):
    """合成 OHLCV (确定性随机游走, 无网络/无缓存)。"""
    rng = np.random.default_rng(seed)
    close = 10.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n)))
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-02', periods=n),
        '开盘': close,
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1_000_000, 2_000_000, n).astype(float),
    })


def _src(name):
    with open(os.path.join(_SKILLS, name), encoding='utf-8') as f:
        return f.read()


class TestGate1ZeroRegression:
    """门禁 #1: 不传 params 且指标列齐全 → 逐位不变 (R5 行为变更单列)。"""

    def test_factory_path_bitwise_unchanged(self):
        from stock_data_fetcher import StockDataFetcher
        df = _ohlcv()
        got = StockDataFetcher().calculate_technical_indicators(df.copy())

        # params 周期列不得混入出厂路径
        assert 'MA_Fast' not in got.columns
        assert 'MA_Slow' not in got.columns

        # 出厂周期逐位 = core 权威公式
        pd.testing.assert_series_equal(
            got['MA5'], core_sma(df['收盘'], 5), check_names=False)
        pd.testing.assert_series_equal(
            got['MA20'], core_sma(df['收盘'], 20), check_names=False)
        pd.testing.assert_series_equal(
            got['RSI'], core_rsi(df['收盘'], 14), check_names=False)
        assert '涨跌幅' in got.columns

        # 显式 None 与缺省同路径
        got2 = StockDataFetcher().calculate_technical_indicators(
            df.copy(), None)
        pd.testing.assert_frame_equal(got, got2)

    def test_identity_missing_columns_still_degrade_to_zero(self):
        # R5 修复只作用于显式映射列; 出厂恒等映射缺列仍降级为 0 (旧行为)
        from signal_generator import SignalGenerator
        out = SignalGenerator().generate_signals(_ohlcv(80))
        assert (out['signal_ma_cross'] == 0).all()
        assert (out['signal_kdj'] == 0).all()
        assert (out['signal_macd'] == 0).all()
        assert 'signal_buy' in out.columns

    def test_generator_from_params_none_is_factory(self):
        from signal_generator import generator_from_params
        g = generator_from_params(None)
        assert g.use_weighted_scoring is False
        assert g.column_map == {}


class TestGate2ParamsDrivePeriods:
    """门禁 #2: 指标周期维随 params 真变 (且出厂锚点并存, R4)。"""

    PERIODS = {
        'ma_fast': 7, 'ma_mid': 15, 'ma_slow': 30,
        'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 5,
        'rsi_period': 21, 'kdj_n': 7, 'bb_period': 15, 'bb_std': 1.8,
        'atr_period': 10,
    }

    def test_indicator_periods_follow_params(self):
        from stock_data_fetcher import StockDataFetcher
        df = _ohlcv(200, seed=11)
        got = StockDataFetcher().calculate_technical_indicators(
            df.copy(), dict(self.PERIODS))

        pd.testing.assert_series_equal(
            got['MA_Fast'], core_sma(df['收盘'], 7), check_names=False)
        pd.testing.assert_series_equal(
            got['MA_Mid'], core_sma(df['收盘'], 15), check_names=False)
        pd.testing.assert_series_equal(
            got['MA_Slow'], core_sma(df['收盘'], 30), check_names=False)

        dif, dea, _hist = core_macd(df['收盘'], 8, 21, 5)
        pd.testing.assert_series_equal(
            got['MACD'], dif, check_names=False)
        pd.testing.assert_series_equal(
            got['MACD_Signal'], dea, check_names=False)

        pd.testing.assert_series_equal(
            got['RSI'], core_rsi(df['收盘'], 21), check_names=False)

        k, _d, _j = core_kdj(df['最高'], df['最低'], df['收盘'], n=7)
        pd.testing.assert_series_equal(got['K'], k, check_names=False)

        upper, _mid, lower, _std = core_bollinger(df['收盘'], 15, 1.8)
        pd.testing.assert_series_equal(
            got['BB_Upper'], upper, check_names=False)
        pd.testing.assert_series_equal(
            got['BB_Lower'], lower, check_names=False)

        pd.testing.assert_series_equal(
            got['ATR'],
            core_atr(df['最高'], df['最低'], df['收盘'], 10),
            check_names=False)
        pd.testing.assert_series_equal(
            got['Vol_MA5'], core_volume_ma(df['成交量'], 5),
            check_names=False)

        # 出厂锚点仍并存 (R4: 选股/技术评分标定网格不随 params)
        pd.testing.assert_series_equal(
            got['MA5'], core_sma(df['收盘'], 5), check_names=False)
        pd.testing.assert_series_equal(
            got['MA60'], core_sma(df['收盘'], 60), check_names=False)

    def test_resolve_params_defaults_and_override(self):
        from indicator_params import resolve_params
        assert resolve_params(None)['ma_fast'] == 5
        assert resolve_params(None)['ma_slow'] == 20
        p = resolve_params({'ma_fast': 12})
        assert p['ma_fast'] == 12
        assert p['ma_slow'] == 20  # 未覆盖键保持出厂默认

    def test_params_route_has_no_hardcoded_periods(self):
        # 源码级: params 路由段周期只来自 p[...] (锚点常量在 ANCHOR_MA_PERIODS)
        src = _src('indicator_params.py')
        assert "eng.ma(int(p['ma_fast']))" in src
        assert "eng.rsi(int(p['rsi_period']))" in src
        assert "eng.atr(int(p['atr_period']))" in src
        assert "eng.macd(int(p['macd_fast']), int(p['macd_slow'])," in src
        assert 'ANCHOR_MA_PERIODS' in src


class TestGate3SignalConsumesParamsColumns:
    """门禁 #3: 信号层经 PARAMS_COLUMN_MAP 真消费 params 周期列 + R5。"""

    @staticmethod
    def _frame(ma_fast, ma_slow):
        """确定性帧: 收盘恒 10 → 趋势档位不干扰交叉断言。"""
        n = len(ma_fast)
        df = pd.DataFrame({
            '日期': pd.bdate_range('2024-01-02', periods=n),
            '开盘': 10.0,
            '最高': 10.5,
            '最低': 9.5,
            '收盘': 10.0,
            '成交量': 1_000_000.0,
        })
        df['MA_Fast'] = ma_fast
        df['MA_Mid'] = ma_fast
        df['MA_Slow'] = ma_slow
        df['MACD'] = 0.0
        df['MACD_Signal'] = 0.0
        df['RSI'] = 50.0
        df['K'] = 50.0
        df['D'] = 50.0
        df['BB_Upper'] = 11.0
        df['BB_Lower'] = 9.0
        return df

    def test_signal_layer_consumes_mapped_ma_slow(self):
        from indicator_params import PARAMS_COLUMN_MAP
        from signal_generator import generator_from_params

        n = 40
        fast = np.full(n, 8.0)
        # A: 慢线在 idx10 下穿快线 → 金叉 +1; B: 慢线恒在快线上方 → 无交叉
        slow_a = np.where(np.arange(n) < 10, 12.0, 7.0)
        slow_b = np.full(n, 9.0)

        gen = generator_from_params({'buy_threshold': 2.0},
                                    column_map=PARAMS_COLUMN_MAP)
        sig_a = gen.generate_signals(
            self._frame(fast, slow_a))['signal_ma_cross']
        sig_b = gen.generate_signals(
            self._frame(fast, slow_b))['signal_ma_cross']

        assert (sig_a == 1).sum() >= 1   # A: 参数化慢线真参与交叉判定
        assert (sig_b != 0).sum() == 0   # B: 同一快线, 慢线不同 → 无交叉

    def test_mapped_missing_column_raises(self):
        from indicator_params import PARAMS_COLUMN_MAP
        from signal_generator import SignalGenerator
        gen = SignalGenerator(column_map=dict(PARAMS_COLUMN_MAP))
        # 裸帧无 MA_Fast/MA_Slow → 显式映射缺失必须抛错 (R5), 不静默降级
        with pytest.raises(ValueError, match='映射列缺失'):
            gen.generate_signals(_ohlcv(60))

    def test_generator_from_params_passes_column_map(self):
        from indicator_params import PARAMS_COLUMN_MAP
        from signal_generator import generator_from_params
        g = generator_from_params({'buy_threshold': 3.0},
                                  column_map=PARAMS_COLUMN_MAP)
        assert g.column_map == PARAMS_COLUMN_MAP
        assert g.buy_threshold == 3.0
        # 不传 column_map → 恒等 (params_delivery 既有用例: factory 列路径)
        g2 = generator_from_params({'buy_threshold': 3.0})
        assert g2.column_map == {}


class TestGate4EngineBSameIndicators:
    """门禁 #4: 主流程指标层 vs 引擎 B `_compute_indicators` 同 params →
    逐位相等 (列名桥接, 非列名归一)。信号层不作逐位断言 (plan §3.8)。"""

    def test_same_params_same_values(self):
        from stock_data_fetcher import StockDataFetcher
        from vectorized_backtest import VectorizedBacktester

        params = dict(TestGate2ParamsDrivePeriods.PERIODS)
        df = _ohlcv(220, seed=13)
        main = StockDataFetcher().calculate_technical_indicators(
            df.copy(), params)
        eng = VectorizedBacktester()._compute_indicators(df.copy(), params)

        pairs = [
            ('MA_Fast', 'ma_fast'), ('MA_Mid', 'ma_mid'),
            ('MA_Slow', 'ma_slow'),
            ('MACD', 'macd'), ('MACD_Signal', 'macd_signal'),
            ('MACD_Hist', 'macd_hist'),
            ('RSI', 'rsi'), ('K', 'k'), ('D', 'd'), ('J', 'j'),
            ('BB_Middle', 'bb_mid'), ('BB_Upper', 'bb_upper'),
            ('BB_Lower', 'bb_lower'),
            ('ATR', 'atr'), ('Vol_MA5', 'vol_ma5'),
        ]
        for a, b in pairs:
            pd.testing.assert_series_equal(
                main[a], eng[b], check_names=False, check_exact=True,
                obj=f'main.{a} vs engineB.{b}')


class TestGate5PositionDims:
    """门禁 #5: 仓位维 (止损/止盈/追踪/仓位比例) 真落到阶段 6/7。"""

    POS = {
        'stop_loss_pct': 0.05, 'take_profit_pct': 0.15,
        'trailing_stop_pct': 0.07, 'position_size_pct': 0.6,
    }

    def test_position_config_from_params(self):
        from backtest_framework import position_config_from_params

        cfg = position_config_from_params(dict(self.POS))
        assert cfg.stop_loss_pct == 0.05
        assert cfg.take_profit_pct == 0.15
        assert cfg.take_profit_enabled is True
        assert cfg.trailing_stop_pct == 0.07
        assert cfg.sizing_value == 0.6

        # 显式覆盖优先 (web 单只仓位滑杆)
        cfg2 = position_config_from_params(dict(self.POS), sizing_value=0.2)
        assert cfg2.sizing_value == 0.2

        # 缺省 = ParameterSpace 出厂 (0.12 / 0.30 / 0.10 / 0.8)
        cfg3 = position_config_from_params(None)
        assert cfg3.stop_loss_pct == 0.12
        assert cfg3.take_profit_pct == 0.30
        assert cfg3.trailing_stop_pct == 0.10
        assert cfg3.sizing_value == 0.8

    def test_position_advice_wires_params(self):
        from core.fetch_result import FetchResult
        from quant_workflow import QuantWorkflow

        class _StubFetcher:
            def get_quote_result(self, symbol, days=120, **kw):
                return FetchResult(ok=True, data=_ohlcv(80, seed=5),
                                  source='stub', as_of='2024-06-01')

            def calculate_technical_indicators(self, df, params=None):
                from stock_data_fetcher import StockDataFetcher
                return StockDataFetcher().calculate_technical_indicators(
                    df, params)

        wf = QuantWorkflow.__new__(QuantWorkflow)  # 跳过 __init__ 副作用
        wf.params = dict(self.POS, atr_period=10)
        wf.fetcher = _StubFetcher()

        adv = wf.position_advice('000001', capital=100000.0)
        assert adv['stop_loss_pct'] == 0.05
        assert adv['take_profit_pct'] == 0.15
        assert adv['trailing_stop_pct'] == 0.07
        assert adv['position_size_pct'] == 0.6
        # min(固定比例风险预算, position_size_pct × capital) 同引擎 B 取小
        assert adv['risk_budget_amount'] == pytest.approx(40000.0)  # 2%/0.05
        assert adv['cap_amount'] == pytest.approx(60000.0)          # 0.6×1e5
        assert adv['suggested_amount'] == pytest.approx(40000.0)
        assert adv['params_source'] == 'optimized'

    def test_portfolio_add_position_registers_stop_params(self):
        from portfolio_manager import PortfolioManager
        mgr = PortfolioManager()
        mgr.create_portfolio('p1', 1_000_000)
        ok = mgr.add_position('p1', '600519', name='moutai', shares=100,
                              price=10.0, stop_loss_pct=0.05,
                              take_profit_pct=0.15, trailing_stop_pct=0.07)
        assert ok
        pos = mgr.stop_monitor.positions['600519']
        assert pos['stop_loss_pct'] == 0.05
        assert pos['take_profit_pct'] == 0.15
        assert pos['trailing_stop_pct'] == 0.07


class TestGate6RegimeSelection:
    """门禁 #6: 自动体制选择 (判定 → 专属体系 / 失败降级全局)。"""

    @staticmethod
    def _systems():
        return [
            {'name': 'global', 'regime': None,
             'params': {'ma_fast': 5, 'ma_slow': 20}},
            {'name': 'bull_only', 'regime': 'BULL',
             'params': {'ma_fast': 13, 'ma_slow': 55}},
        ]

    def _write_json(self, tmp_path):
        path = tmp_path / 'opt.json'
        path.write_text(
            json.dumps({'use_weighted_scoring': True,
                        'systems': self._systems()}),
            encoding='utf-8')
        return str(path)

    @staticmethod
    def _write_index(tmp_path, n=300):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        close = 1000.0 * np.power(1.005, np.arange(n))  # 单边上行 → 合法体制
        df = pd.DataFrame({
            '日期': pd.bdate_range('2023-01-02', periods=n),
            '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
            '收盘': close,
            '成交量': np.full(n, 1e8),
        })
        df.to_parquet(mgr._get_index_path('000300'), index=False)
        return df

    def test_current_market_regime_reads_local_index(self, tmp_path):
        from optimized_params import current_market_regime
        self._write_index(tmp_path)
        reg = current_market_regime(data_dir=str(tmp_path))
        assert reg in REGIME_LABELS

    def test_current_market_regime_no_data_returns_none(self, tmp_path):
        from optimized_params import current_market_regime
        # 空目录 → 无本地指数 → None (不臆造体制)
        assert current_market_regime(data_dir=str(tmp_path)) is None

    def test_auto_hits_regime_system(self, tmp_path):
        from optimized_params import resolve_regime_params
        params, info = resolve_regime_params(
            self._write_json(tmp_path), regime='auto',
            current_regime='BULL', with_info=True)
        assert params['ma_fast'] == 13
        assert info['regime_used'] == 'BULL'
        assert info['fallback'] is False

    def test_auto_falls_back_to_global_when_no_match(self, tmp_path):
        from optimized_params import resolve_regime_params
        params, info = resolve_regime_params(
            self._write_json(tmp_path), regime='auto',
            current_regime='SIDEWAYS', with_info=True)
        assert params['ma_fast'] == 5
        assert info['fallback'] is True
        assert info['regime_used'] is None

    def test_auto_without_detection_falls_back_global(
            self, tmp_path, monkeypatch):
        import optimized_params as op
        monkeypatch.setattr(op, 'current_market_regime',
                            lambda *a, **k: None)
        params, info = op.resolve_regime_params(
            self._write_json(tmp_path), regime='auto', with_info=True)
        assert params['ma_fast'] == 5
        assert info['fallback'] is True

    def test_auto_composition_detection_then_selection(self, tmp_path):
        # 端到端组合: 本地指数判定 → auto 选择 (判定结果显式传入, 保持
        # current_market_regime 默认 data_dir 语义不被测试污染)
        from optimized_params import (current_market_regime,
                                      resolve_regime_params)
        self._write_index(tmp_path)
        reg = current_market_regime(data_dir=str(tmp_path))
        assert reg in REGIME_LABELS
        params, info = resolve_regime_params(
            self._write_json(tmp_path), regime='auto',
            current_regime=reg, with_info=True)
        assert params['ma_fast'] in (5, 13)
        if reg == 'BULL':
            assert params['ma_fast'] == 13
            assert info['fallback'] is False


class TestGate7SourceLevel:
    """门禁 #7: 源码级接线 (签名/调用点/缺口文档化) + 图表 R3 口径。"""

    def test_fetcher_params_signature(self):
        src = _src('stock_data_fetcher.py')
        assert ('def calculate_technical_indicators(self, df, params=None):'
                in src)
        assert 'compute_params_indicators' in src

    def test_web_three_call_sites_pass_params(self):
        src = _src('web_app.py')
        assert src.count(
            'calculate_technical_indicators(data, '
            'st.session_state.optimized_params)') == 3
        assert 'resolve_regime_params' in src
        assert 'column_map=PARAMS_COLUMN_MAP' in src
        assert 'position_config_from_params' in src

    def test_quant_workflow_wiring(self):
        src = _src('quant_workflow.py')
        # 阶段 2 两处指标调用 (quick_analysis / full_analysis) 传 self.params
        assert src.count('result.data, self.params)') == 2
        assert 'column_map=PARAMS_COLUMN_MAP' in src
        assert 'def position_advice' in src

    def test_engine_a_min_holding_gap_documented(self):
        # 引擎 A 无 min_holding_days 出场闸门 — 只文档化, 不新造 (plan §8.1)
        src = _src('backtest_framework.py')
        assert 'def position_config_from_params(' in src
        assert 'min_holding_days' in src  # docstring 缺口说明

    def test_chart_ma_resolution_prefers_params_columns(self):
        from chart_visualizer import _resolve_ma
        df = _ohlcv(30)
        df['MA5'] = 1.0
        df['MA_Fast'] = 2.0

        # params 列优先 (与信号同口径, R3)
        s, label = _resolve_ma(df, 5)
        assert label == 'MA_Fast'
        assert (s == 2.0).all()

        # 缺 params 列 → 回退出厂锚点列
        s2, label2 = _resolve_ma(df.drop(columns=['MA_Fast']), 5)
        assert label2 == 'MA5'
        assert (s2 == 1.0).all()

        # 裸帧 → 回退现场自算 (旧行为)
        df3 = _ohlcv(30)
        s3, label3 = _resolve_ma(df3, 5)
        assert label3 == 'MA5'
        pd.testing.assert_series_equal(
            s3, core_sma(df3['收盘'], 5), check_names=False)
