# -*- coding: utf-8 -*-
"""
优化结果 → 生产参数下发契约

读取 OptimizationEngine.save_results 落盘的 best_params JSON, 提取
systems[].params 作为可直接下发的参数字典:

    params = load_optimized_params('stock_data/optimization_result.json')
    generator = SignalGenerator(use_weighted_scoring=params['use_weighted_scoring'],
                                scoring_params=params)
    metrics = VectorizedBacktester().backtest(data, params)

选择规则:
    regime=None → 优先全局系统 (regime 为空/'GLOBAL'), 其次唯一系统;
                  多个非全局系统时要求显式 regime= (不猜)
    regime=X    → 精确匹配 systems[].regime, 无匹配报错并列出可用值

加权模式标注: 优先显式 use_weighted_scoring 参数; None 时取 JSON 顶层
字段 (save_results 落盘); 旧 JSON 缺键 → True (当前优化器
默认 — 评分维参与 fitness 的运行产出的是加权模式最优解)。
"""
import json


def _select_system(systems, regime):
    """按 regime 选择 system 条目。返回 (index, system); 失败抛 ValueError。"""
    if not systems:
        raise ValueError("优化结果 JSON 无 systems 条目 — 空结果或非 save_results 落盘格式")

    def _is_global(sys):
        r = sys.get('regime')
        return r is None or r == 'GLOBAL'

    if regime is not None:
        for i, s in enumerate(systems):
            if s.get('regime') == regime:
                return i, s
        available = [s.get('regime') for s in systems]
        raise ValueError(f"regime={regime!r} 无匹配 system; 可用: {available}")

    for i, s in enumerate(systems):
        if _is_global(s):
            return i, s
    if len(systems) == 1:
        return 0, systems[0]
    regimes = [s.get('regime') for s in systems]
    raise ValueError(
        f"结果含多个体制系统 {regimes} 且无全局系统 — 请传 regime= 指定其一")


def list_systems(filepath):
    """列出 JSON 内全部 system 的选择摘要 (name/regime/fitness)。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    summary = []
    for s in data.get('systems') or []:
        fs = s.get('fitness_scores') or {}
        summary.append({
            'name': s.get('name'),
            'regime': s.get('regime'),
            'fitness': max(fs.values()) if fs else None,
            'fitness_scores': fs,
            'applicable_regimes': s.get('applicable_regimes'),
            'sample_count': s.get('sample_count'),
        })
    return summary


def load_optimized_params(filepath, regime=None, use_weighted_scoring=None):
    """下发入口: 返回可直接喂给回测/信号层的参数字典。

    Parameters:
    -----------
    filepath : str
        OptimizationEngine.save_results 落盘的 JSON
    regime : str or None
        体制系统选择 (None = 全局/唯一系统)
    use_weighted_scoring : bool or None
        覆盖返回参数中的模式开关; None 时取 JSON 顶层字段 (缺键 → True)

    Returns:
    --------
    dict: systems[].params + use_weighted_scoring 标注
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    idx, system = _select_system(data.get('systems') or [], regime)

    params = system.get('params')
    if not isinstance(params, dict) or not params:
        raise ValueError(f"system[{idx}] params 缺失或为空 — 结果文件不完整")

    # 软校验: 未知键仅警告不阻断 (参数空间前向兼容)
    try:
        from parameter_space import ParameterSpace
        known = set(ParameterSpace.get_param_names())
        unknown = sorted(set(params) - known)
        if unknown:
            print(f"[WARN] params 含参数空间未知键 (跳过校验): {unknown}")
    except ImportError:
        pass

    if use_weighted_scoring is None:
        use_weighted_scoring = bool(data.get('use_weighted_scoring', True))

    out = {**params, 'use_weighted_scoring': use_weighted_scoring}
    print(f"[OK] 已加载优化参数: system[{idx}] name={system.get('name')!r} "
          f"regime={system.get('regime')!r} n_params={len(params)} "
          f"use_weighted_scoring={use_weighted_scoring}")
    return out


def current_market_regime(data_dir="./stock_data", index_code="000300"):
    """按当前大盘体制打标签 (离线优先, 无网络依赖)。

    口径: 本地指数行情 (`historical/index/` parquet → quotes CSV,
    `HistoricalDataManager.load_index` 三级中的前两级, 不联网) →
    `market_regime_classifier.MarketRegimeClassifier.classify` (与优化结果
    的 regime_labels 同一标签体系: BULL/BEAR/SIDEWAYS/CRASH/RECOVERY)。

    Returns:
    --------
    str | None: 最后一根交易日的体制标签; 无本地指数数据/数据过短/任何
    异常 → None (调用方降级全局 + 如实提示, 不臆造体制)。
    """
    try:
        from historical_data_manager import HistoricalDataManager
        from market_regime_classifier import MarketRegimeClassifier

        mgr = HistoricalDataManager(data_dir=data_dir)
        df = mgr.load_index(index_code)
        if df is None or len(df) == 0:
            print(f"[WARN] 本地无指数 {index_code} 数据 → 体制判定不可用")
            return None

        clf = MarketRegimeClassifier(data_dir=data_dir)
        clf.index_data = df
        regimes = clf.classify()
        if regimes is None or len(regimes) == 0:
            return None
        return str(regimes.iloc[-1])
    except Exception as e:  # 数据缺失/过短 → 如实降级, 不阻断参数加载
        print(f"[WARN] 体制判定失败 ({e}) → 不可用")
        return None


def resolve_regime_params(filepath, regime='auto', current_regime=None,
                          use_weighted_scoring=None, with_info=False):
    """按体制选择参数 (regime='auto' 时自动判定 + 全局降级)。

    Parameters:
    -----------
    filepath : str
        save_results 落盘 JSON
    regime : str | 'auto' | None
        'auto' → 用 current_market_regime() 判定 (或调用方传入
        current_regime), 命中专属体系用之, 否则降级全局 (regime=None);
        其余同 load_optimized_params (None=全局优先, 字符串=精确匹配)
    current_regime : str | None
        调用方已判定的体制 (跳过重复判定); 'auto' 模式专用
    with_info : bool
        True → 返回 (params, info); info 含 regime_used/system_name/fallback

    Returns:
    --------
    dict | (dict, dict): load_optimized_params 口径的参数字典
    """
    if regime != 'auto':
        params = load_optimized_params(filepath, regime=regime,
                                       use_weighted_scoring=use_weighted_scoring)
        if with_info:
            return params, {'regime_requested': regime, 'regime_used': regime,
                            'system_name': None, 'fallback': False}
        return params

    cur = current_regime if current_regime is not None else current_market_regime()
    fallback = False
    used = None
    if cur:
        try:
            params = load_optimized_params(filepath, regime=cur,
                                           use_weighted_scoring=use_weighted_scoring)
            used = cur
        except ValueError:
            print(f"[WARN] 当前体制 {cur!r} 无专属体系 → 降级全局")
            params = load_optimized_params(filepath, regime=None,
                                           use_weighted_scoring=use_weighted_scoring)
            fallback = True
    else:
        print("[WARN] 体制判定不可用 → 降级全局")
        params = load_optimized_params(filepath, regime=None,
                                       use_weighted_scoring=use_weighted_scoring)
        fallback = True

    if with_info:
        return params, {'regime_requested': 'auto', 'regime_used': used,
                        'system_name': None, 'fallback': fallback}
    return params
