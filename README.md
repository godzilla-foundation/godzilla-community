<div align="center">

# godzilla.dev

[![License](https://img.shields.io/badge/License-Apache%202.0-informational.svg)](https://github.com/godzilla-foundation/godzilla-community/blob/master/LICENSE)
[![Youtube](https://img.shields.io/youtube/channel/subscribers/UCxzzdEnDRbylLMWmaMjywOA)](https://www.youtube.com/@godzilla-dev)

**godzilla.dev is an open-source C++/Python infrastructure for self-hosted crypto funding rate arbitrage and market making, with ultra low-latency architecture and enterprise private deployment.**

[Documentation](https://godzilla.dev/documentation/) · [Whitepaper](./WHITEPAPER.md) · [Installation](https://godzilla.dev/documentation/installation/) · [FAQ](https://godzilla.dev/documentation/faq/) · [Enterprise](https://godzilla.dev/enterprise/)

</div>

---

## What is godzilla.dev?

godzilla.dev is **not a retail trading bot** — it is production-grade trading infrastructure. It combines an ultra low-latency **C++ execution core** with a flexible **Python strategy layer**, and is designed to run **co-located** next to exchange matching engines (e.g. AWS availability zones used by major exchanges).

Trading teams and individual quants use godzilla.dev to run:

- **Funding rate arbitrage** — delta-neutral spot–perp and cross-exchange funding rate strategies on centralized exchanges
- **Market making** — ultra low-latency pure market making that quotes both sides of the book
- **Custom low-latency strategies** — any automated strategy built on the same execution core

The codebase is free and publicly available under the **Apache 2.0** license. Our mission is to democratize high-frequency trading: infrastructure that was once exclusive to quant funds, now open to everyone.

## Why godzilla.dev?

- **C++ execution core.** Order placement, cancellation, and market data handling run in C++ for microsecond-level tick-to-trade latency — while strategies stay in Python for fast iteration. In the reproducible journal-only benchmark ([WHITEPAPER.md](WHITEPAPER.md)), the native path shows a median tick-to-trade of ~125 μs measured on a commodity laptop-class CPU; co-located server hardware with tuned kernels represents a different operating point.
- **Self-hosted and private.** godzilla.dev is local software, not a web platform. Your API keys, private keys, and strategy configuration never leave machines you control.
- **Co-location ready.** Installed from source and managed with `pm2`, following the same workflow you use to deploy on a co-located AWS machine.
- **Open source, community-driven.** Exchange connectors and strategy templates are maintained by the Godzilla Foundation together with a global community of algo traders.
- **Enterprise private deployment.** For funds and funding rate arbitrage teams that need a fully self-hosted stack with support, see [godzilla.dev Enterprise](https://godzilla.dev/enterprise/).

## How is godzilla.dev different from typical bot frameworks?

| | godzilla.dev | Typical Python bot frameworks |
|---|---|---|
| Execution core | C++ (Python strategy layer) | Pure Python |
| Latency profile | Designed for co-located, microsecond-level HFT | Second/millisecond-level, latency-tolerant strategies |
| Deployment | Self-hosted, co-location first | Local or cloud, latency not a design goal |
| Primary use cases | Funding rate arbitrage, HFT market making | Grid/DCA bots, general automation |
| Target users | Prop traders, market makers, arbitrage teams | Retail users, hobbyists |

Frameworks like Hummingbot are excellent for breadth of connectors and community strategies; godzilla.dev focuses on **latency-critical, self-hosted execution** for professional market making and arbitrage.

## Getting started

1. Read the [Installation guide](https://godzilla.dev/documentation/installation/) — we recommend installing from source, the same way you deploy to a co-located machine.
2. Explore the [Strategies documentation](https://godzilla.dev/documentation/strategies/) and run your first strategy.
3. Follow the [Learning series](https://godzilla.dev/learning/) — step-by-step tutorials from Python basics to AI-assisted quant workflows.

## Community

- [Telegram community](https://godzilla.dev/documentation/community/) — connect with other algo traders and get help
- [YouTube @godzilla-dev](https://www.youtube.com/@godzilla-dev) — tutorials and walkthroughs
- [FAQ](https://godzilla.dev/documentation/faq/) — answers to common questions

All official Godzilla Foundation code lives in repositories under [this GitHub organization](https://github.com/godzilla-foundation). Please download godzilla.dev software only from these official sources.

See [BRAND.md](./BRAND.md) for official descriptions and press assets

## License

Apache 2.0 — free for personal, research, and commercial use, including forks and private modifications.

---

<div align="center">

## 中文简介

</div>

**godzilla.dev 是一个开源的 C++/Python 基础设施，用于自托管（self-hosted）的加密货币资金费率套利与做市，具备超低延迟架构，并支持企业级私有化部署。**

godzilla.dev 不是零售型交易机器人，而是生产级的交易基础设施：C++ 撮合级低延迟执行内核 + Python 策略层，为交易所同机房（co-location）部署而设计。交易团队和个人量化交易者用它来运行：

- **资金费率套利** —— 现货–永续、跨交易所的 Delta 中性资金费策略
- **做市** —— 超低延迟的双边挂单做市
- **自定义低延迟策略** —— 基于同一执行内核构建任意自动化策略

代码库基于 **Apache 2.0** 开源许可证免费公开。我们的使命是让高频交易民主化：把曾经只属于量化基金的基础设施，开放给每一个人。

企业级私有化部署（面向资金费率套利团队与机构）请见 [godzilla.dev Enterprise](https://godzilla.dev/enterprise/)。

[阅读完整文档](https://godzilla.dev/documentation/) · [Whitepaper](./WHITEPAPER.md)

## Citation

If you use godzilla.dev or the benchmark artifact in your research, please cite:

Kun Xue. *Low-Latency Execution Infrastructure for Funding-Rate Arbitrage:
Architecture and a Reproducible Single-Host Benchmark.* 2026.
Benchmark artifact: https://doi.org/10.5281/zenodo.21307411