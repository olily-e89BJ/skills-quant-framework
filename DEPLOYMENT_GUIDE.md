# 部署指南

## 系统要求

- Python 3.11+（CI 覆盖 3.11 / 3.12）
- 操作系统：macOS / Linux / Windows 均可
- 磁盘：本地数据缓存（`stock_data/`）按股票数量增长，预留数 GB 起

## 安装

```bash
git clone <repo>
cd skills-quant-framework

# 分析层依赖（必需）
pip install -r .claude/skills/requirements.txt

# Web 界面依赖（可选）
pip install -r web_requirements.txt
```

依赖分三层，缺失时行为不同：

| 层 | 依赖 | 缺失时 |
|----|------|--------|
| 核心 | pandas, numpy, scipy, akshare | 对应模块 ImportError |
| 运行时 | pyarrow（Parquet 缓存）, requests（实时行情） | 自动降级为 CSV / 实时行情不可用 |
| 可选 | matplotlib（绘图）, scikit-learn（ML）, streamlit（Web） | 对应功能降级，核心流程不受影响 |

**数据真相在本地 Parquet**，无外部数据库依赖。缓存目录 `stock_data/` 可随时删除强制重新取数。

## 首次部署：预取数据

新环境无存量缓存，先预取（联网操作）：

```bash
# 批量拉取股票池日线（默认后复权）
python .claude/skills/historical_data_manager.py batch --adjust hfq

# 交易日历来源（可选，用于停牌识别）：拉取指数行情
python .claude/skills/historical_data_manager.py fetch --index 000001

# 退市股补齐（幸存者偏差证据）
python .claude/skills/historical_data_manager.py delisted refresh
python .claude/skills/historical_data_manager.py delisted fetch
```

## 运行

### Web 界面

```bash
python run_web_app.py
# 等价于: streamlit run .claude/skills/web_app.py --server.port 8501
```

访问 http://localhost:8501。Streamlit 自带生产服务器，**不需要** gunicorn/uvicorn。

长期运行用 systemd（Linux）：

```ini
# /etc/systemd/system/skills-app.service
[Unit]
Description=Skills Quant Web App
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/skills-quant-framework
ExecStart=/path/to/venv/bin/streamlit run .claude/skills/web_app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now skills-app
```

### 分析脚本

所有脚本从仓库根目录运行（模块按裸名导入，依赖相对路径）：

```bash
python .claude/skills/historical_data_manager.py fetch 600519
python .claude/skills/quant_workflow.py --help
```

### 测试

```bash
python3 -m pytest tests/ -q    # 990 个离线测试
```

## Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r .claude/skills/requirements.txt -r web_requirements.txt
EXPOSE 8501
CMD ["streamlit", "run", ".claude/skills/web_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

数据缓存挂载为卷，避免容器重建丢缓存：

```yaml
services:
  app:
    build: .
    ports: ["8501:8501"]
    volumes:
      - ./stock_data:/app/stock_data
    restart: unless-stopped
```

## 升级

```bash
git pull
pip install -r .claude/skills/requirements.txt -r web_requirements.txt
python3 -m pytest tests/ -q     # 升级后跑测试确认
```

数据缓存无需迁移：列名/口径由代码侧统一映射（`core/dataframe.py`），旧缓存自动兼容。若需切换复权口径，用 `batch --adjust hfq` 增量补齐。

## 故障排查

**端口被占用**：`lsof -i :8501`，或换端口 `streamlit run .claude/skills/web_app.py --server.port 8502`。

**ImportError（裸模块名找不到）**：确认从仓库根目录运行；或 `export PYTHONPATH="$PWD:$PWD/.claude/skills"`。

**取数失败**：检查网络；新浪/akshare 接口偶发不可用时框架会如实报错（`FetchResult.ok=False`），不会静默返回空数据。

**并行取数崩溃（V8/解密）**：新浪 KLC 载荷解密依赖 V8 isolate，非线程安全；框架已内置进程级闸门（`js_runtime.py`），正常调用无需干预。
