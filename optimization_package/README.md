# 技术分析指标优化工具 - 部署包

> ⚠️ **`skills/` 是构建产物, 不是真相源** (2026-10-26 治理决策, 审计 H3 批次4)
>
> - 唯一真相源 = 仓库主链 `.claude/skills/`; 本目录的 `skills/` 由
>   `pack.py` **自动生成** (依赖闭包扫描 + 整包复制 `core/`)。
> - **包内文件请勿手改** —— 每个文件头都带"由 pack.py 自动生成"戳,
>   下次打包即被覆盖。
> - 每次打包写 `skills/PROVENANCE.json`: 源 commit + 生成时间 + 每文件
>   sha256 → 部署包自带"来自哪个版本"的证据; 可用
>   `python -c "import json;print(json.load(open('skills/PROVENANCE.json'))['source_commit'])"`
>   核对来源版本, 避免把**陈旧产物**当成最新用。
> - 本目录的 **`skills/` 与 `stock_data/` gitignored** (前者是构建产物, 后者是
>   数据) → 克隆仓库后需重跑 `pack.py` 才有 `skills/`; 部署脚本本身入库。

## 概述

本工具通过遗传算法(GA)对A股30年历史数据进行多轮次优化，为不同市场体制(牛市/熊市/震荡/暴跌/反弹)分别找到最优技术分析参数，产出多套指标体系。

**优化目标**: 6-18个月持有期，正收益率，>80%概率超10%收益。

> 注: 该目标的诚实性依赖主链已落地的口径修正 —— 样本外隔离 (H1: 参数选择
> 只用 IS 窗口, OOS 仅报告)、稳健性证据 (H10: 试验次数/随机基线分位数/
> Top-k 离散/bootstrap CI)、confidence 证据派生 (H2)、引擎侧停牌建模
> (H5)、因子层点时口径 (H6)、point-in-time 股票池 (H4)、验证链重做 (H3)。
> **这些修复只在主链**; 旧版本副本不含它们, 故不要用旧包产出的参数。

## 目录结构

```
optimization_package/
├── README.md               # 本文档
├── requirements.txt        # Python依赖
├── (打包脚本在主链)         # .claude/skills/tools/pack.py (受版本控制)
├── fetch_data.py           # 阶段1: 数据获取(需联网)
├── run_optimize.py         # 阶段2: 参数优化(离线)
├── skills/                 # 核心模块(**由 pack.py 生成, 请勿手改**)
│   ├── PROVENANCE.json     #   来源版本戳 (commit + sha256)
│   ├── core/               #   共享单一真相源 (指标/绩效/信号契约/日历/停牌)
│   ├── market_regime_classifier.py   # 大盘态势分类
│   ├── historical_data_manager.py    # Parquet数据管理
│   ├── parameter_space.py            # 26维参数空间
│   ├── vectorized_backtest.py        # 向量化回测引擎
│   ├── optimization_engine.py        # GA优化引擎
│   ├── multi_stock_backtester.py     # 多股票回测
│   ├── optimization_config.py        # 配置管理
│   ├── daily_signal_generator.py     # 每日信号生成
│   ├── indicator_system_report.py    # 报告生成
│   └── ...                           # 其他依赖模块(自动收录)
└── stock_data/             # 数据目录(运行后生成)
    ├── historical/         # Parquet历史数据
    ├── delisted/           # 退市股清单 (幸存者偏差前提)
    ├── regime_labels.csv   # 大盘体制标签
    ├── optimization_result.json  # 优化结果
    └── reports/            # 优化报告
```

## 快速开始

### 1. 环境准备

```bash
# 安装Python依赖
pip install -r requirements.txt

# 验证安装
python -c "import pandas, numpy, akshare, pyarrow; print('OK')"
```

### 2. 打包(在原项目目录运行)

```bash
cd Stocks
python .claude/skills/tools/pack.py
```

这会按**依赖闭包**把主链模块复制到 `optimization_package/skills/`
(含 `core/` 子包), 并写 `PROVENANCE.json`。
之后将整个 `optimization_package/` 目录复制到目标电脑。

> 打包脚本在**主链内** (`.claude/skills/tools/pack.py`, 受版本控制) ——
> 构建工具本身必须被跟踪, 否则"产物=主链构建物"的约定无法复现/评审。

### 3. 数据获取(需联网, 约2-4小时)

```bash
# 获取500只股票 + 大盘指数 + 体制标签
python fetch_data.py

# 或获取更多 (短选项 -n 与 --n 等价)
python fetch_data.py --n 1000
python fetch_data.py -n 100

# 或全量A股(~5000只, 约8-12小时)
python fetch_data.py --full

# 指定股票
python fetch_data.py --symbols 000001 600519
```

> **路径与当前目录无关**: 脚本所有路径以脚本所在目录 (`__file__`) 为基准
> (清单 `skills/stock_list.csv`、数据目录 `stock_data/`), 因此整目录拷到
> 任意机器/任意目录都能直接跑; 从仓库根执行
> `python optimization_package/fetch_data.py` 同样可用。
>
> **幸存者偏差**: 30年回测的股票池必须含**当时已退市**的股票, 否则池子
> 带幸存者偏差。脚本默认联网刷新退市名录 (上交所+深交所, 两市都成功才
> 落盘) 并把在范围退市股一并纳入取数; 清单不可用时会显式告警。
> 已有清单可用 `--refresh-delisted` 强制刷新 (清单有效期 90 天);
> `--no-delisted` 可跳过 (代价: 股票池有偏)。
>
> 退市股单独一批处理 (end_date = 各自退市日; 本地已是终态 → 直接跳过):
> 退市股在退市日之后**不再交易**, 若按"今天"做增量, 增量窗口恒为空 →
> 接口如实返回空 → 每次重跑都刷 "API无新数据/失败" 警告并白发请求
> (新浪限流 → 整批卡死)。脚本末尾会打印幸存者偏差证据
> (`幸存者偏差: 否 (已消除)` 即池子含当时已退市的股票)。

### 4. 参数优化(离线, 约4-8小时)

```bash
# 标准优化(推荐)
python run_optimize.py

# 快速测试(约30分钟)
python run_optimize.py --preset quick

# 深度优化(约8-12小时)
python run_optimize.py --preset thorough

# 自定义参数
python run_optimize.py --n-stocks 80 --pop 100 --gen 50 --mode full
```

### 5. 查看结果

```bash
# 优化结果
cat stock_data/optimization_result.json

# 文本报告
cat stock_data/reports/indicator_systems.txt

# HTML报告(浏览器打开)
start stock_data/reports/indicator_systems.html
```

### 6. 复制结果回原项目

```bash
# 将以下文件复制回原项目的 stock_data/ 目录
cp stock_data/optimization_result.json /原项目路径/stock_data/
cp stock_data/reports/* /原项目路径/stock_data/reports/
```

## 详细说明

### 优化模式

| 模式 | 说明 | 耗时 |
|------|------|------|
| `global` | 全局优化，找通用基线参数 | ~1h |
| `regime` | 按体制分别优化，找体制专属参数 | ~2h |
| `robust` | 稳健优化，找跨体制都不差的参数 | ~1h |
| `iterative` | 多轮迭代精炼 | ~2h |
| `full` | 完整流程: 全局→体制→稳健→迭代 | ~6h |

### 预设配置

| 预设 | 种群 | 代数 | 样本 | 耗时 | 适用场景 |
|------|------|------|------|------|----------|
| `quick` | 30 | 10 | 20 | ~30min | 验证流程 |
| `standard` | 100 | 50 | 50 | ~4h | 日常优化 |
| `production` | 100 | 50 | 80 | ~6h | 生产环境 |
| `thorough` | 150 | 80 | 100 | ~10h | 最终优化 |

### 参数空间(25维)

**指标参数 (13个)**:
- MA: fast(3-30), mid(10-60), slow(15-120)
- MACD: fast(6-20), slow(18-40), signal(5-15)
- RSI: period(5-30), oversold(15-40), overbought(60-85)
- KDJ: n(5-21)
- BB: period(10-40), std(1.0-3.5)
- ATR: period(7-28)

**评分权重 (4个)**: 趋势/动量/风险/近期表现

**信号阈值 (4个)**: 买入/卖出信号强度, 综合评分阈值

**仓位参数 (4个)**: 止损(3-15%)/止盈(10-50%)/仓位(30-100%)/追踪止损(3-10%)

### 适应度函数

```
fitness = 0.40 * 达标率(>10%收益)
        + 0.25 * 中位收益率
        + 0.20 * 中位夏普比率
        + 0.15 * 回撤惩罚(越小越好)
```

### Walk-Forward验证

- 训练窗口: 504天(约2年)
- 测试窗口: 180天(约6个月)
- 步进: 63天(约3个月)
- 30年数据约产生110个样本外窗口

## 预期输出

优化完成后产出类似以下的多套指标体系:

```
==============================================================================
  指标体系 #1: "牛市追涨型"
  适用场景: 大盘处于上升趋势，MA60>MA120，市场情绪乐观
==============================================================================
  历史表现:
    中位收益率: +18.3%
    超10%收益概率: 87%
    中位夏普比: 1.42
    中位最大回撤: -12.1%

  指标参数:
    MA: fast=8, slow=30
    MACD: fast=10, slow=24, signal=7
    RSI: period=10, oversold=35, overbought=75
    评分权重: 趋势40% + 动量30% + 风险10% + 近期表现20%
    买入阈值: score>=55  止损/止盈: 8%/25%

==============================================================================
  指标体系 #2: "熊市防御型"
  适用场景: 大盘处于下降趋势，MA60<MA120，市场恐慌
==============================================================================
  ...

==============================================================================
  指标体系 #3: "震荡市高抛低吸型"
  适用场景: 大盘横盘整理，无明确方向
==============================================================================
  ...

==============================================================================
  指标体系 #4: "通用稳健型"
  适用场景: 不确定市场方向时的默认策略
==============================================================================
  ...
```

## 故障排除

**Q: 报"[ERROR] 无股票列表, 请用 --symbols 指定"**
- 说明包内 `skills/stock_list.csv` 缺失 → 跑一次打包:
  `python .claude/skills/tools/pack.py` (在原项目目录)
- 或用 `--symbols` 显式指定代码
- 注意: 清单按脚本所在目录查找, 与当前工作目录无关 —— 若确实存在却仍报错,
  检查是不是把 `fetch_data.py` 单独拷走了 (它依赖同目录的 `skills/`)

**Q: akshare获取数据失败**
- 检查网络连接
- 尝试增加 `--delay 0.5`
- 部分股票可能已退市，属正常跳过

**Q: 报"[WARN] xxx API无新数据/失败, 返回本地旧数据" 是不是出错了?**
- 对**退市股**不是错误: 退市股在退市日之后不再交易 → 接口如实返回"没有
  新数据" → 脚本返回本地完整历史 (截止最后交易日, 那就是它的全部)
- 脚本已把退市股单独一批处理 (end_date=各自退市日; 本地已是终态 → 跳过)
  → 这类噪音不再出现
- 若出现在**在册股**上: 该股确实取不到新数据 (长期停牌/接口异常) → 重跑
  即可增量补齐; 末尾的"无缓存数据"清单会列出来

**Q: 批量取数跑到一半卡住不动**
- 原因: 新浪限流后 akshare 内部的 `requests.get` (无超时) 挂住 → 工作线程
  永久阻塞, 整批再也不返回
- 脚本已给 requests 兜底超时 (`--http-timeout`, 默认30秒) → 卡死会变成该股
  取数失败并如实列出; 被限流时调大 `--delay` (如 0.8) 并重跑 (增量补齐)

**Q: 报"幸存者偏差: 是 (股票池有偏)"**
- 退市股行情没补齐 (清单缺失/过期/有缺股) → 池子缺当时已退市的股票
- 按提示补齐: `python fetch_data.py --refresh-delisted` 后重跑

**Q: 优化太慢**
- 使用 `--preset quick` 先验证流程
- 减少 `--n-stocks` 或 `--pop` / `--gen`
- 每代约5分钟(15个体), 50代约4小时

**Q: 内存不足**
- 减少 `--n-stocks` (每只股票约占1MB内存)
- 使用64位Python

**Q: 优化结果不理想**
- 增加样本量 `--n-stocks 100`
- 增加代数 `--gen 80`
- 检查体制标签是否合理

## 文件说明

| 文件 | 用途 |
|------|------|
| `optimization_result.json` | 优化产出的多套指标体系(核心产物) |
| `regime_labels.csv` | 大盘每日体制标签 |
| `regime_report.txt` | 体制分类统计报告 |
| `delisted/delisted_list.csv` | 退市股名录 (幸存者偏差证据, 有效期90天) |
| `reports/indicator_systems.*` | 可读的优化报告(text/md/html) |
| `historical/*.parquet` | 股票历史数据缓存 |
