# -*- coding: utf-8 -*-
"""
阶段1: 数据获取脚本 (需要联网)

功能:
1. 获取A股股票列表 (默认本地清单抽样, 可拉全量)
2. 批量下载30年历史数据 (Parquet格式)
3. 获取大盘指数数据并生成体制标签
4. 数据验证 (含幸存者偏差证据)

运行:
    python fetch_data.py                    # 默认获取500只
    python fetch_data.py --n 1000           # 获取1000只
    python fetch_data.py -n 100             # 同上 (短选项)
    python fetch_data.py --symbols 000001 600519  # 指定股票
    python fetch_data.py --full             # 全量A股(~5000只)
    python fetch_data.py --refresh-delisted # 联网刷新退市清单 (幸存者偏差前提)

预计耗时: 500只约2小时, 全量约8-12小时

路径约定: 本脚本的所有路径一律以**脚本所在目录** (__file__) 为基准, 与
当前工作目录无关 —— 部署包整目录拷到任意机器/任意目录都能直接跑。
旧实现用 CWD 相对路径 (`Path('skills/stock_list.csv')`、`--data-dir
stock_data`) → 从仓库根执行 `python optimization_package/fetch_data.py`
时找不到清单 → 报"无股票列表, 请用 --symbols 指定" (默认 500 只同样
中招); 更糟的是数据会写进**主链**的 stock_data/ (同名目录, 同名 parquet
布局) → 污染主链缓存。
"""
import sys
import argparse
import random
from pathlib import Path

# --- 路径基准 (__file__ 相对, 与 CWD 无关) ---------------------------
# 部署包根 = 本脚本所在目录; skills/ = 包内模块目录 (pack.py 生成的产物)
PKG_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PKG_ROOT / 'skills'
# 数据目录默认落在**包内** —— 绝不用 CWD 相对的 'stock_data' (主链同名
# 目录会被静默污染)
DEFAULT_DATA_DIR = PKG_ROOT / 'stock_data'

# 退市股"本地已完结"的判定容差 (天): 交易所名录记的是退市决议/摘牌日,
# 比最后交易日晚几天到几周 → 缓存最后交易日落在退市日前 90 天内即视为
# 已覆盖到退市期 (退市股之后不再交易 → 历史是终态)
DELISTED_COMPLETE_SLACK_DAYS = 90

# 确保skills目录在路径中
sys.path.insert(0, str(SKILLS_DIR))

from historical_data_manager import HistoricalDataManager
from market_regime_classifier import MarketRegimeClassifier


def load_stock_list_codes() -> list:
    """本地股票清单 → 6位代码列表 (路径全部 __file__ 基准)

    优先用包内 `stock_list_manager` 单例 (其路径基于该模块自身 __file__),
    读不出再按候选路径直接读 CSV。
    """
    try:
        from stock_list_manager import get_stock_list
        df = get_stock_list().get_all_stocks()
        if df is not None and len(df) and 'code' in df.columns:
            codes = [str(c).strip().zfill(6) for c in df['code'].tolist()]
            if codes:
                return codes
    except Exception as e:  # noqa: BLE001 — 清单读不出只是降级, 不该崩
        print(f"[WARN] stock_list_manager 读取失败: {e}")

    candidates = [
        SKILLS_DIR / 'stock_list.csv',                       # 部署包内 (pack.py 拷入)
        PKG_ROOT.parent / '.claude' / 'skills' / 'stock_list.csv',  # 主链 (仓库内直接跑)
        Path('skills') / 'stock_list.csv',                   # 旧 CWD 相对路径 (兼容)
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            import pandas as pd
            df = pd.read_csv(path, encoding='utf-8-sig', dtype={'code': str})
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 读取 {path} 失败: {e}")
            continue
        col = 'code' if 'code' in df.columns else '股票代码'
        if col not in df.columns:
            continue
        codes = [str(c).strip().zfill(6) for c in df[col].tolist()]
        print(f"[INFO] 股票清单: {path} ({len(codes)} 只)")
        return codes
    return []


def patch_requests_timeout(timeout=15):
    """给 requests 兜底超时 —— akshare 内部的 requests 调用**不传 timeout**

    实测 (2026-11-05): 批量取数跑到 ~310 只后, 新浪限流, akshare
    `stock_zh_a_daily` 里的 `requests.get(...)` 无超时 → 工作线程永久
    挂住 → 4 个线程全挂 → 整批取数**再也不返回** (主线程在
    `future.result()` 上死等, try/except 拦不住)。

    这里只给**没显式传 timeout** 的调用补一个默认值 (已传的不动) → 限流
    时抛 Timeout → 被 batch_fetch 的 except 记为 FAIL → 该股缺失如实
    暴露, 下一轮重跑增量补齐 (fetch_and_cache 只补缺失区间)。

    Returns:
        bool: 是否已安装 (已安装或 timeout<=0 时返回 False)
    """
    if timeout is None or timeout <= 0:
        return False
    try:
        import requests
    except ImportError:
        return False
    if getattr(requests.get, '_qf_timeout_patched', False):
        return False

    orig_get, orig_post = requests.get, requests.post

    def _get(url, *args, **kw):
        kw.setdefault('timeout', timeout)
        return orig_get(url, *args, **kw)

    def _post(url, *args, **kw):
        kw.setdefault('timeout', timeout)
        return orig_post(url, *args, **kw)

    requests.get = _get
    requests.post = _post
    requests.get._qf_timeout_patched = True
    print(f"[INFO] requests 默认超时: {timeout}s (akshare 内部调用不传超时)")
    return True


def load_delisted_registry(data_dir, refresh=False):
    """退市清单 (幸存者偏差的前提) —— 返回 DelistedRegistry 或 None

    退市股是**点时股票池**的一部分: 只用当前上市名录 → 当时已退市的
    股票不在池内 → 股票池带幸存者偏差 (主链 `get_universe_meta` 据此
    标记 `survivorship_bias`)。清单缺失 = 没查过, 不等于没有偏差。
    """
    try:
        from delisted_stocks import DelistedRegistry, default_registry_path
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 退市清单模块不可用: {e}")
        return None

    path = default_registry_path(data_dir)
    reg = DelistedRegistry.load(path)
    if refresh or not reg.available:
        print("[INFO] 联网刷新退市清单 (上交所+深交所, 两市都成功才落盘)...")
        try:
            reg.refresh()
            print(f"[OK] 退市清单已刷新 → {path}")
        except Exception as e:  # noqa: BLE001 — 旧清单不动, 如实告警
            print(f"[WARN] 退市清单刷新失败: {e}")
            if not reg.available:
                return None
    return reg


def delisted_pairs(reg) -> list:
    """退市清单 → [(代码, 退市日 'YYYYMMDD')] (在范围A股)

    退市日用交易所名录里的日期 (比最后交易日晚几天到几周 —— 名录记的是
    决议/摘牌日)。这里用它做**取数窗口的上界**, 不是"最后交易日"。
    """
    import pandas as pd
    frame = getattr(reg, '_frame', None)
    if frame is None or len(frame) == 0:
        frame = pd.read_csv(reg.path, encoding='utf-8-sig', dtype={'code': str})
    pairs = []
    for _, row in frame.iterrows():
        if not bool(row.get('in_scope', True)):
            continue          # B股等不在框架股票池范围
        code = str(row['code']).strip().zfill(6)
        day = pd.to_datetime(row.get('delist_date'), errors='coerce')
        if pd.isna(day):
            continue          # 退市日期缺失 → 无法定窗口, 不猜
        pairs.append((code, day.strftime('%Y%m%d')))
    return pairs


def cached_last_dates(dm) -> dict:
    """已缓存股票 → (基础代码 → 最后交易日) (元数据口径)"""
    out = {}
    for key, info in dm.metadata.get('stocks', {}).items():
        base, _, tag = str(key).rpartition('_')
        code = base if base and tag in ('qfq', 'hfq') else str(key)
        last = info.get('last_date')
        if last:
            out[code] = last
    return out


def fetch_delisted_stocks(dm, pairs, args):
    """退市股取数 —— 退市股的历史是**终态**, 按"今天"增量必空

    退市股在退市日之后不再交易 → 用 batch_fetch 的统一 end_date=今天 做
    增量, 增量窗口恒为空 → 接口如实返回空 → 每次重跑都刷
    "API无新数据/失败, 返回本地旧数据" 警告, 而且白发一次请求 (新浪
    限流 → 批量取数整批卡死, 实测 2026-11-05)。

    三档处置:
      1. 本地无数据 → 按退市日取全量历史 (首次取数, 正常路径, 无警告);
      2. 本地有数据且最后交易日距退市日 ≤ 90 天 → **已完结** → 跳过
         (退市日是决议/摘牌日, 与最后交易日常差几天到几周);
      3. 本地有数据但距退市日 > 90 天 (长期停牌后才摘牌) → 探一次接口:
         有新数据 (停牌期间复牌过) → 增量补齐; 无新数据 → 确认完结跳过。
    """
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sina_daily import fetch_daily, format_symbol
    from core.fetch_result import DEFAULT_ADJUST

    cached = cached_last_dates(dm)
    todo, skipped = [], 0
    for code, end in pairs:
        last = cached.get(code)
        if not last:
            todo.append((code, end, None))     # 首次取数
            continue
        try:
            gap = (pd.to_datetime(end) - pd.to_datetime(last)).days
        except Exception:  # noqa: BLE001 — 日期坏 → 当作"需探针"
            gap = None
        if gap is None or gap <= DELISTED_COMPLETE_SLACK_DAYS:
            skipped += 1
            continue
        todo.append((code, end, last))          # 需探针

    print(f"[INFO] 退市股 {len(pairs)} 只 → 待取 {len(todo)} 只, "
          f"本地已完结跳过 {skipped} 只")
    if not todo:
        return

    def _one(item):
        code, end, last = item
        if last:
            # 探针: 长期停牌期间是否复牌过 (退市股的常态是"没有新数据")
            try:
                probe = fetch_daily(
                    symbol=format_symbol(code),
                    start_date=pd.to_datetime(last) + pd.Timedelta(days=1),
                    end_date=pd.to_datetime(end),
                    adjust=DEFAULT_ADJUST)
            except Exception:  # noqa: BLE001 — 探针失败 ≠ 有新数据
                probe = None
            if probe is None or len(probe) == 0:
                return code, 'complete'   # 确认完结 (无新数据 → 不请求、不刷警告)
        try:
            # _persist_metadata=False: 并发写同一个 metadata.json 会互相
            # 覆盖 (主链 batch_fetch 同款约定) → 由主线程统一落盘
            df = dm.fetch_and_cache(code, start_date=args.start,
                                    end_date=end, _persist_metadata=False)
            return code, ('ok' if df is not None and len(df) else 'empty')
        except Exception as e:  # noqa: BLE001 — 单股失败不该中断整批
            print(f"[WARN] {code} 取数失败: {str(e)[:100]}")
            return code, 'fail'

    ok = complete = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_one, it) for it in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            code, status = fut.result()
            if status == 'ok':
                ok += 1
            elif status == 'complete':
                complete += 1
            else:
                fail += 1
                print(f"[WARN] {code} 无数据 ({status})")
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {code} "
                      f"(成功:{ok} 完结:{complete} 失败:{fail})")

    dm._save_metadata()
    print(f"[OK] 退市股取数完成: 成功 {ok}, 确认完结 {complete}, 失败 {fail}")


def fetch_stock_data(args):
    """获取股票历史数据"""
    # akshare 内部 requests 不传超时 → 新浪限流时线程永久挂死 (整批卡住)
    patch_requests_timeout(args.http_timeout)

    dm = HistoricalDataManager(args.data_dir)

    # 确定股票列表
    symbols = []
    if args.symbols:
        symbols = [str(s).strip().zfill(6) for s in args.symbols]
    elif args.full or args.n > 500:
        # 从akshare获取全部A股列表
        print("[INFO] 获取A股全部股票列表...")
        import akshare as ak
        try:
            df = ak.stock_zh_a_spot_em()
            symbols = [str(c).zfill(6) for c in df['代码'].tolist()]
            print(f"[OK] 获取到 {len(symbols)} 只A股")
        except Exception as e:
            print(f"[WARN] 获取股票列表失败: {e}")
            print("[INFO] 尝试从本地stock_list.csv加载...")
            symbols = load_stock_list_codes()
    else:
        # 从本地列表随机抽样
        all_symbols = load_stock_list_codes()
        if not all_symbols:
            print("[ERROR] 无股票列表, 请用 --symbols 指定")
            print(f"       (已查找: {SKILLS_DIR / 'stock_list.csv'})")
            return
        n = min(args.n, len(all_symbols))
        if args.seed is not None:
            random.seed(args.seed)
        symbols = random.sample(all_symbols, n)

    if not symbols:
        print("[ERROR] 无股票可获取")
        return

    # 退市股单独一批 (幸存者偏差); --no-delisted 才跳过
    # (显式 --symbols = 用户点名要的清单 → 不擅自加料)
    delisted = []
    if not args.no_delisted and not args.symbols:
        reg = load_delisted_registry(args.data_dir, refresh=args.refresh_delisted)
        if reg is not None and reg.available:
            delisted = delisted_pairs(reg)
            print(f"[INFO] 纳入在范围退市股 {len(delisted)} 只 (幸存者偏差前提)")
        else:
            print("[WARN] 退市清单不可用 → 股票池带幸存者偏差 "
                  "(刷新: python fetch_data.py --refresh-delisted)")

    print(f"\n{'='*60}")
    print(f"  数据获取计划")
    print(f"  股票数: {len(symbols)} (在册) + {len(delisted)} (退市)")
    print(f"  日期范围: {args.start} ~ 今天")
    print(f"  并发数: {args.workers}")
    print(f"  请求间隔: {args.delay}s")
    print(f"  数据目录: {Path(args.data_dir).resolve()}")
    print(f"{'='*60}\n")

    # 批量获取 (在册股; end_date=今天 → 增量到最新)
    dm.batch_fetch(
        symbols,
        start_date=args.start,
        max_workers=args.workers,
        delay=args.delay,
    )

    # 保存元数据
    dm._save_metadata()

    # 退市股单独取数 (end_date=各自退市日; 本地已完结 → 跳过)
    if delisted:
        fetch_delisted_stocks(dm, delisted, args)

    # 验证数据质量 (含幸存者偏差证据)
    print("\n[INFO] 验证数据质量...")
    try:
        meta = dm.get_universe_meta(min_rows=2000)
    except Exception as e:  # noqa: BLE001 — 证据层失败不该掩盖取数结果
        print(f"[WARN] 股票池证据核查失败: {e}")
        meta = {}

    universe = meta.get('universe') or []
    print(f"[OK] 有足够历史的股票: {len(universe)} 只")

    if 'survivorship_bias' in meta:
        bias = meta['survivorship_bias']
        print(f"[{'WARN' if bias else 'OK'}] 幸存者偏差: "
              f"{'是 (股票池有偏)' if bias else '否 (已消除)'}")
        print(f"       {meta.get('survivorship_note', '')}")

    # 缺数的股如实列出 (取数失败/限流/新股历史短) —— 重跑本脚本即增量补齐
    cached = set(dm.get_all_symbols())
    requested = list(symbols) + [c for c, _ in delisted]
    missing = [s for s in requested if s not in cached]
    if missing:
        head = ', '.join(missing[:15])
        print(f"[WARN] {len(missing)}/{len(requested)} 只无缓存数据: {head}"
              f"{' ...' if len(missing) > 15 else ''}")
        print("       (重跑本脚本即增量补齐; 新浪限流时建议调大 --delay)")

    return universe


def fetch_index_data(args):
    """获取大盘指数数据并生成体制标签"""
    print("\n" + "=" * 60)
    print("  获取大盘指数数据 + 体制分类")
    print("=" * 60)

    classifier = MarketRegimeClassifier(args.data_dir)

    # 加载沪深300指数
    index_data = classifier.load_index_data(
        index_code=args.index,
        start_date=args.start,
    )

    if index_data is None or len(index_data) == 0:
        print("[ERROR] 无法获取指数数据")
        # 尝试从已有的股票数据中构建
        print("[INFO] 尝试从股票数据估算大盘态势...")
        return

    # 体制分类
    print("\n[INFO] 进行体制分类...")
    regime_series = classifier.classify(method='adaptive')

    # 保存标签
    labels_file = Path(args.data_dir) / 'regime_labels.csv'
    classifier.save_labels(labels_file, regime_series)

    # 输出报告
    report = classifier.format_report(regime_series)
    report_file = Path(args.data_dir) / 'regime_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[OK] 体制报告: {report_file}")

    # 打印摘要
    print(report[:500])
    print("...")


def build_parser() -> argparse.ArgumentParser:
    """命令行解析器 (独立成函数 → 可被门禁直接调用, 不必跑 main)"""
    parser = argparse.ArgumentParser(description='阶段1: 数据获取')
    parser.add_argument('--symbols', nargs='+', help='指定股票代码')
    parser.add_argument('--n', '-n', type=int, default=500,
                        help='随机获取N只 (默认500)')
    parser.add_argument('--full', action='store_true', help='全量A股')
    parser.add_argument('--start', default='19960101', help='开始日期')
    parser.add_argument('--index', default='000300', help='大盘指数代码')
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR),
                        help=f'数据目录 (默认: {DEFAULT_DATA_DIR})')
    parser.add_argument('--workers', type=int, default=4, help='并发数')
    parser.add_argument('--delay', type=float, default=0.3, help='请求间隔(秒)')
    parser.add_argument('--http-timeout', type=float, default=30,
                        help='HTTP请求超时秒数 (0=不设; 防新浪限流卡死整批)')
    parser.add_argument('--skip-index', action='store_true', help='跳过指数数据获取')
    parser.add_argument('--seed', type=int, default=None,
                        help='抽样随机种子 (可复现)')
    parser.add_argument('--refresh-delisted', action='store_true',
                        help='联网刷新退市清单 (幸存者偏差前提)')
    parser.add_argument('--no-delisted', action='store_true',
                        help='不纳入退市股 (股票池将带幸存者偏差)')
    return parser


def main():
    args = build_parser().parse_args()

    # Step 1: 获取股票数据
    print("\n" + "=" * 60)
    print("  阶段1: 股票历史数据获取")
    print("=" * 60)
    universe = fetch_stock_data(args)

    # Step 2: 获取指数数据 + 体制标签
    if not args.skip_index:
        fetch_index_data(args)

    # 完成
    print("\n" + "=" * 60)
    print("  数据获取完成!")
    print("=" * 60)
    print(f"  数据目录: {Path(args.data_dir).resolve()}")
    print(f"  下一步: python run_optimize.py")
    print("=" * 60)

    # 显式回收: py_mini_racer 的 isolate 在解释器退出期才释放会抛
    # "PythonFinalizationError: cannot join thread at interpreter shutdown"
    # (解释器关闭阶段的噪音, 非取数失败) → 趁解释器还活着回收掉
    import gc
    gc.collect()


if __name__ == "__main__":
    main()
