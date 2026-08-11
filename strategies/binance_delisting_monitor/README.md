# Binance 下架公告监控

每天抓一次币安公告，筛出下架（delisting）相关的通知，只输出上次运行之后的新增项。

## 安装

```bash
pip install -r requirements.txt
```

## 用法

```bash
python3 binance_delisting_monitor.py                  # 抓一次，输出新增的下架公告
python3 binance_delisting_monitor.py --all            # 忽略状态，输出全部命中项
python3 binance_delisting_monitor.py --json           # JSON 输出
python3 binance_delisting_monitor.py --catalog 161    # 只扫 Delisting 分区
python3 binance_delisting_monitor.py --pages 3        # 每个分区翻 3 页（首次建库用）
python3 binance_delisting_monitor.py --selftest       # 只测接口连通性
```

第一次跑会把当前所有命中项当成「新增」全部输出，之后每天只输出增量。想要一份干净的
起始基线，可以先跑一次 `--pages 5 > /dev/null` 把历史灌进状态文件。

## 网络

公告接口只在 `www.binance.com` 上提供（`api.binance.com` 的 `/bapi/*` 会直接 403）。
在国内网络下这个域名会被 TLS 重置，**必须让代理接管 binance.com**：

```bash
python3 binance_delisting_monitor.py --proxy http://127.0.0.1:7897
# 或
export BINANCE_PROXY=http://127.0.0.1:7897
```

跑 `--selftest` 可以先确认代理是否生效。注意：即使系统已经设了 `https_proxy`，
如果代理软件（Clash 等）的规则里把 binance.com 判成了 DIRECT，一样会被重置——
需要在代理规则里把它改成走节点。

## 告警推送

支持飞书 / 钉钉 / 企业微信 / Slack 机器人，按 URL 自动识别消息格式：

```bash
python3 binance_delisting_monitor.py --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
export BINANCE_WEBHOOK_URL=...   # 也可以用环境变量
```

## 定时运行

cron（推荐，每天 09:00）：

```cron
0 9 * * * cd /home/kunxue/dev/godzilla.dev.notice && /usr/bin/python3 binance_delisting_monitor.py --proxy http://127.0.0.1:7897 >> monitor.log 2>&1
```

或者常驻进程：

```bash
python3 binance_delisting_monitor.py --interval 86400
```

## 判定规则

标题命中 `DELIST_PATTERNS`（delist / remove / cease trading / 下架 / 停止交易 …）
且不命中 `EXCLUDE_PATTERNS`（取消下架 / 恢复交易 …）即算下架公告，同时从标题里
提取涉及的币种代码。规则都在脚本顶部，可以直接改，也可以用
`--keyword` / `--exclude` 追加自定义正则。

只看标题不看正文，所以像 `Notice on Removal of Spot Trading Pairs` 这种标题里
不带币种的公告，`symbols` 会是空的，需要点开链接看正文。

## 文件

| 文件 | 说明 |
| --- | --- |
| `binance_delisting_monitor.py` | 主程序 |
| `state/seen.json` | 已上报公告的状态，删掉会导致下次全量重报 |
| `--out` 指定的 JSONL | 可选，追加保存每条命中的公告，做历史归档 |
