# -*- coding: utf-8 -*-
"""
部署包脚本 (`optimization_package/fetch_data.py` / `run_optimize.py`) 的
路径与参数门禁

背景 (2026-11-05 实测): `fetch_data.py` 用 **CWD 相对** 路径找股票清单
(`Path('skills/stock_list.csv')`) 与数据目录 (`--data-dir stock_data`) →

- 从仓库根执行 `python optimization_package/fetch_data.py` → 找不到清单
  → 报"[ERROR] 无股票列表, 请用 --symbols 指定" (默认 500 只同样中招,
  `-n 100` 也一样);
- 更糟: 取数写进**主链** `stock_data/` (同名目录 + 同名 parquet 布局) →
  静默污染主链缓存。

本门禁锁定:
- 清单 / 数据目录按**脚本所在目录** (`__file__`) 解析 → 与 CWD 无关;
- `-n` 短选项可用 (用户习惯敲 `-n 100`);
- 阶段1 与阶段2 的默认路径互相指认 (同一 data-dir / regime-labels /
  output) → 从任意目录跑两端都能接上;
- 阶段1 默认纳入退市股 (幸存者偏差前提), 并报告偏差状态。

**为什么用子进程**: 脚本 import 时会把包内 `skills/` 插到 sys.path 首位
→ 同名模块 (historical_data_manager / core.*) 会顶掉主链版本, 污染同
一 pytest 会话里的其它用例 → 探针一律跑在独立子进程里。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = REPO_ROOT / 'optimization_package'
FETCH_SCRIPT = PKG_DIR / 'fetch_data.py'
OPT_SCRIPT = PKG_DIR / 'run_optimize.py'
PKG_SKILLS = PKG_DIR / 'skills'

# 探针: 加载脚本 → 解析参数 → 读股票清单 (cwd 由调用方指定, 用来证明
# 与当前工作目录无关)
PROBE_FETCH = r'''
import importlib.util, json
spec = importlib.util.spec_from_file_location("fd", {script!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
codes = m.load_stock_list_codes()
args = m.build_parser().parse_args({argv!r})
print(json.dumps({{
    "n_codes": len(codes),
    "sample": codes[:3],
    "n": args.n,
    "data_dir": args.data_dir,
    "no_delisted": args.no_delisted,
    "pkg_root": str(m.PKG_ROOT),
    "default_data_dir": str(m.DEFAULT_DATA_DIR),
}}))
'''

PROBE_OPT = r'''
import importlib.util, json
spec = importlib.util.spec_from_file_location("ro", {script!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
args = m.build_parser().parse_args({argv!r})
print(json.dumps({{
    "data_dir": args.data_dir,
    "regime_labels": args.regime_labels,
    "output": args.output,
    "default_data_dir": str(m.DEFAULT_DATA_DIR),
}}))
'''


def _run_probe(code: str, cwd: Path) -> dict:
    """跑探针 (独立子进程) → 解析其 JSON 输出"""
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=str(cwd), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f'探针失败:\n{proc.stdout}\n{proc.stderr}'
    payload = proc.stdout.strip().splitlines()[-1]
    return json.loads(payload)


@pytest.fixture(scope='module', autouse=True)
def _require_packed_package():
    """包内 skills/ 是 pack.py 的构建产物 (gitignored) —— 没打包就跳过"""
    if not PKG_SKILLS.is_dir():
        pytest.skip('工作区无优化部署包 (先跑: python .claude/skills/tools/pack.py)')
    if not (PKG_SKILLS / 'stock_list.csv').is_file():
        pytest.skip('包内无 stock_list.csv (重新打包)')


class TestPathIndependence:
    """路径必须按脚本所在目录解析, 与 CWD 无关"""

    def test_stock_list_found_from_any_cwd(self, tmp_path):
        """换个工作目录仍能找到股票清单 (旧实现必然找不到)"""
        out = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=[]),
            cwd=tmp_path)
        assert out['n_codes'] > 1000, f'清单读不到: {out}'
        assert all(len(c) == 6 and c.isdigit() for c in out['sample'])

    def test_data_dir_default_is_package_relative(self, tmp_path):
        """默认数据目录 = 包内 stock_data (绝对) —— 不落到 CWD / 主链同名目录"""
        out = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=[]),
            cwd=tmp_path)
        data_dir = Path(out['data_dir'])
        assert data_dir.is_absolute(), '默认数据目录必须是绝对路径'
        assert data_dir == Path(out['pkg_root']) / 'stock_data'
        assert data_dir == Path(out['default_data_dir'])

    def test_stage2_reads_stage1_output(self, tmp_path):
        """阶段2 的默认 data-dir / regime-labels / output 与阶段1 同源"""
        fetch = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=[]),
            cwd=tmp_path)
        opt = _run_probe(
            PROBE_OPT.format(script=str(OPT_SCRIPT), argv=[]),
            cwd=tmp_path)
        assert Path(opt['data_dir']) == Path(fetch['data_dir'])
        assert Path(opt['regime_labels']) == \
            Path(fetch['data_dir']) / 'regime_labels.csv'
        assert Path(opt['output']) == \
            Path(fetch['data_dir']) / 'optimization_result.json'


class TestArgs:
    """命令行契约"""

    def test_short_n_alias(self, tmp_path):
        """`-n 100` 与 `--n 100` 等价 (用户按短选项敲)"""
        short = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=['-n', '100']),
            cwd=tmp_path)
        long = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=['--n', '100']),
            cwd=tmp_path)
        assert short['n'] == 100 == long['n']

    def test_default_n_is_500(self, tmp_path):
        out = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=[]),
            cwd=tmp_path)
        assert out['n'] == 500

    def test_delisted_included_by_default(self, tmp_path):
        """默认纳入退市股 (幸存者偏差前提); 可显式跳过"""
        out = _run_probe(
            PROBE_FETCH.format(script=str(FETCH_SCRIPT), argv=[]),
            cwd=tmp_path)
        assert out['no_delisted'] is False
