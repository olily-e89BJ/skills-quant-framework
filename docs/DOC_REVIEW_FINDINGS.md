# 文档与解释文字审查台账

本次改造的目标：把文档与代码注释从「修改过程叙事」（审计编号 / 批次 / 旧实现对比）改写为「正向设计说明」——写清楚系统是什么、算法怎么算、依据是什么。不改任何代码逻辑。

处理状态：`待处理` / `已删除` / `已重写` / `已修正` / `保留`。

改写规范（适用于全部代码注释与文档）：

1. 正向陈述：写"是什么口径 + 为什么"，不写"审计 X 修了旧实现 Y"。
2. 算法依据保留并显式化（公式 + 口径选择理由）。
3. 票号引用（审计 H1 / 批次 2 / 台账 §x）一律删除；历史线索只留在台账 `OPEN_ITEMS_PLAN_2026-10-25.md`。
4. 不用 AI 腔（"值得注意的是 / 综上所述 / 深入 / 全面提升"等），简洁直述。
5. 改注释前必须核对该文件相关的门禁断言（`tests/` 中的 `in src` / `__doc__` 文本断言），改写后必须继续满足。

---

## 一、删除的历史文档（状态：已删除）

| 文件 | 问题 |
|---|---|
| `docs/FEBRUARY_COMPLETION_REPORT.md` | 2026-02 开发过程报告，与当前系统脱节 |
| `docs/FEBRUARY_DEV_SUMMARY.md` | 同上 |
| `docs/FEBRUARY_DEVELOPMENT_PLAN.md` | 同上 |
| `docs/MARCH_COMPLETION_REPORT.md` | 2026-03 开发过程报告 |
| `docs/MARCH_DEVELOPMENT_PLAN.md` | 同上 |
| `docs/MARCH_DEVELOPMENT_SUMMARY.md` | 同上 |
| `docs/SKILLS_DEVELOPMENT_SUMMARY.md` | 开发历程总结，过程性文档 |
| `docs/SKILLS_ENHANCEMENT_REPORT.md` | 模块增强报告（过程） |
| `docs/SKILLS_ENHANCEMENT_SUMMARY.md` | 同上 |
| `docs/SKILLS_FIX_REPORT.md` | 数据模块修正报告（过程） |
| `docs/SKILLS_REORGANIZATION_REPORT.md` | 目录整理报告（过程） |
| `docs/SKILLS_TEST_REPORT.md` | 一次性测试报告 |
| `docs/BACKTEST_ENHANCEMENT_REPORT.md` | 模块增强报告（过程） |
| `docs/CHART_VISUALIZER_REPORT.md` | 同上 |
| `docs/MULTI_FACTOR_ENHANCEMENT_REPORT.md` | 同上 |
| `docs/PORTFOLIO_MANAGER_REPORT.md` | 同上 |
| `docs/UNIT_TEST_FRAMEWORK_REPORT.md` | 同上 |
| `docs/DATA_UPDATE_REPORT.md` | 一次性数据更新报告 |
| `docs/DAHUA_POSITION_REPORT_v2.md` | 一次性个股分析 |
| `docs/HOT_STOCKS_RECOMMENDATION.md` | 同上 |
| `docs/OPERATION_STRATEGY_000568_600893.md` | 同上 |
| `docs/QUANT_ANALYSIS_5STOCKS.md` | 同上 |
| `docs/SIGNAL_GENERATOR_TEST_REPORT.md` | 同上 |
| `docs/STOCK_SELECTION_REPORT.md` | 同上 |
| `docs/strategy_report_002678_002983.md` | 同上 |
| `.claude/skills/ROADMAP.md` | 2026-02 开发计划，模块状态表已严重过时（如列 test_tool.py、漏列全部后续模块） |
| `.claude/skills/量化交易完善规划.md` | 历史规划，未反映当前架构 |

## 二、文档合并（状态：已重写）

| 原文件 | 处理 |
|---|---|
| `API_REFERENCE.md` (v1) + `API_REFERENCE_V2.md` (v2) | 合并为单一 `API_REFERENCE.md`，按当前模块重写；删除 V2 |
| `.claude/skills/README_完整功能清单.md` + `README_量化交易Skills.md` | 合并为 `README_功能清单.md`；旧两份含已删模块（concurrent_fetcher/database_manager）与过时行数统计 |

## 三、重写的活文档（状态：已重写）

发现的过时事实（重写时已修正）：

| 文件 | 发现的问题 |
|---|---|
| `README.md` | 写"14 个功能模块 / 9,200+ 行"（实际 38+ 模块、29k+ 行）；依赖列表含已删除的 redis/psycopg2；模块表含删除线残留 |
| `QUICK_START_GUIDE.md` | 链接指向已删文档；示例部分过时 |
| `DEPLOYMENT_GUIDE.md` | 基本可用，修链接 |
| `docs/skills_layers.md` | 内容合格，但通篇票号叙事（审计 C-P2-16 / 项 21 / 台账 §x）→ 改为自洽架构说明 |
| `docs/USER_MANUAL_V2.md` | 引用已删除的 concurrent_fetcher（3 处）、BatchFetcher → 按当前模块重写 |
| `docs/USAGE_EXAMPLES.md` | 示例部分过时 → 核对重写 |
| `docs/ANALYSIS_WORKFLOW.md` | 引用不存在的 `quant_analysis_workflow.py` → 按当前入口重写 |
| `docs/FAQ.md` | 部分条目过时 → 核对修正 |
| `.claude/skills/USER_GUIDE.md` | 2026-02 版本，模块表/状态过时 → 重写为当前系统指南 |
| `.claude/skills/README_股票数据工具.md` | 核对修正 |
| `CHANGELOG.md` | 只修悬空链接（历史记录性质，叙事保留） |

## 四、代码注释正向化（状态：已重写）

门禁风险清单（改注释前必须核对的源码文本断言）：

- `tests/test_h3_validation_chain.py`：`HistoricalBacktestValidator.__doc__` 须含"不做回测"。
- `tests/test_h5_suspension.py`：`execution_model` 源码须含"停牌"、不得含"不虚构交易日历"；4 引擎须含 `core.suspension`。
- `tests/test_project_metadata.py`：`core/indicators.vwap` 与 `trend_indicators.vwap` 的 docstring 不得写"当日/单日"。
- `tests/test_source_hygiene.py`：`parameter_space.py` 的 `ParameterSpace` docstring 参数计数格式（`共N个可优化参数`、`指标参数 (N个)` 等）必须与实际 ParamDef 一致。
- `tests/test_index_namespace.py`：`core/trading_calendar.py` 须含 `mgr.load_index('000001')`。
- 其余 `assert X in src` 类断言（delisted_stocks / historical_data_manager / optimization_engine 等）改注释时逐文件复查。

处理进度：

| 批次 | 文件 | 状态 |
|---|---|---|
| A | `core/` 全部（indicators / metrics / signal / trading_calendar / fetch_result / dataframe / suspension / indicator_engine / __init__） | 已完成 |
| B | optimization_engine / historical_data_manager / historical_backtest_validator / vectorized_backtest / backtest_framework / multi_factor_selection | 已完成 |
| C | 其余 ~33 个含票号叙事的 skills 文件 | 已完成 |

## 六、最终验证（全部通过）

- `python3 -m pytest tests/ -q`：**990 passed**（基线不变，门禁全绿）。
- 代码注释票号叙事残留扫描：`rg '审计|台账|批次|E-P/C-P/P0/H/M/L/D1...' .claude/skills/*.py` → 0 处（唯一命中为 `multi_stock_backtester.py` 的字符串 `"【收益BOTTOM5】"` 正则误匹配，非票号）。
- 结构等价校验：剥离 docstring + 字符串常量归一化后，56/56 个 skills Python 文件与基线 `acb49f1` AST 逐字节一致 → **仅改注释/docstring/提示文本，零逻辑变化**。
- 运行时字符串变更（help 文本、告警、错误消息中的票号）：已确认 `tests/` 无对这些字符串的断言。
- 悬空链接扫描：根目录 7 份入口文档 + `docs/*.md` + `.claude/skills/*.md` 的相对 markdown 链接全部可解析。

## 五、轻改的契约文档（状态：已修正）

| 文件 | 处理 |
|---|---|
| `AGENTS.md` | 修正过时事实（LOC ~27k→28.5k、模块数 38+→43、concurrent_fetcher 历史叙述删除）；契约表/票号↔测试文件名对照保留（票号是门禁测试的索引 key） |
| `CLAUDE.md` | 修正过时事实（依赖补 scipy、pytest pythonpath、测试布局：删除不存在的 test_integration/test_new_modules 引用、依赖表补 scipy）；票号叙事（审计 #18 / E-P1 #19）改正向表述 |
| `docs/OPEN_ITEMS_PLAN_2026-10-25.md` | 不动（审计台账，历史记录性质） |
| `tests/` | 不动（用户决策） |
