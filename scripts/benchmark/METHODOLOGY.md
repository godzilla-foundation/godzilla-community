# Benchmark Methodology

## Scope

This benchmark measures software-stack tick-to-trade latency inside godzilla.dev under a controlled local replay environment.

It does not measure exchange network latency, exchange matching latency, fill probability, strategy profitability, connector coverage, ease of use, or long-term production reliability.

The current v1 benchmark evaluates godzilla.dev only. Cross-system comparisons such as Hummingbot are planned for a later version after the measurement framework and raw schemas are stable.

## System Under Test

The current native benchmark stack is:

- native mock market data extension (`GZ_MOCK_MD_NATIVE=1`)
- native benchmark strategy (`strategies/benchmark_cpp`)
- native mock trader (`GZ_MOCK_TD_NATIVE=1`)
- Kungfu journal analysis (`analysis/summarize_latency_journal.py`)

The benchmark runs on one machine and uses local shared-memory journals for event transport and measurement.

## Metric Definition

The primary metric is tick-to-trade software-stack latency:

```text
total_tick_to_trade_ns = order report gen_time - matched depth gen_time
```

The journal analyzer currently reports:

| Metric | Definition |
| --- | --- |
| `md_to_order_input_ns` | `order_input_gen_time_ns - depth_gen_time_ns` |
| `order_report_ns` | `order_gen_time_ns - order_input_gen_time_ns` |
| `total_tick_to_trade_ns` | `order_gen_time_ns - depth_gen_time_ns` |

These are journal-frame timestamps, not wall-clock timestamps from an external exchange.

## Matching Model

The analyzer joins events as follows:

1. Depth to OrderInput:
   - primary: `(symbol, side, price)` match
   - fallback: nearest prior depth by journal `gen_time`
2. OrderInput to Order:
   - primary: `order_id`
   - fallback: nearest later order by journal `gen_time`

The joined CSV records `join_depth_method` and `join_order_method` for every row so matching can be audited.

A strict depth `event_id` to order-input join is not yet available because `OrderInput` does not currently carry `depth.data_time` through the standard `Context::insert_order` API.

## Native Mock Market Data

Native mock MD publishes synthetic top-of-book `Depth` messages after strategy subscription.

Important controls:

| Variable | Meaning |
| --- | --- |
| `GZ_MOCK_MD_INTERVAL_NS` | Publish interval in nanoseconds. |
| `GZ_MOCK_MD_MAX_EVENTS` | Maximum number of depth events to publish. `0` means unlimited. |
| `GZ_MOCK_MD_MAX_BATCH` | Number of depth events per publish loop iteration. |
| `GZ_MOCK_MD_SPIN_NS` | Optional sleep+spin wait window to reduce timer tail latency. |

The depth event id is stored in `Depth.data_time` and appears in the joined output as `depth_event_id`.

## Warm-up

Use `--skip-first` or `GZ_BENCH_ANALYSIS_SKIP_FIRST` to discard early joined rows from summary statistics. The default one-shot command uses `100`.

The raw joined CSV still contains the post-skip rows only. The summary metadata includes both `joined_rows_raw` and `joined_rows`.

## CPU Affinity

`run.sh` supports optional CPU affinity via `taskset -pc` after each PM2 process starts.

| Variable | Process |
| --- | --- |
| `GZ_BENCH_CORE_MASTER` | `benchmark_master` |
| `GZ_BENCH_CORE_LEDGER` | `benchmark_ledger` |
| `GZ_BENCH_CORE_MD` | `benchmark_md_mock` |
| `GZ_BENCH_CORE_TD` | `benchmark_td_mock:benchmark` |
| `GZ_BENCH_CORE_STRATEGY` | `benchmark_strategy_cpp` |

Unset variables leave the default scheduler behavior unchanged.

## Reproduction Command

Recommended v1 one-shot command:

```bash
cd ~/dev/godzilla-community/scripts/benchmark

GZ_BENCH_TRACE_MODE=journal \
GZ_MOCK_MD_INTERVAL_NS=300000 \
GZ_MOCK_MD_MAX_EVENTS=5000 \
GZ_MOCK_MD_SPIN_NS=50000 \
GZ_BENCH_CORE_MASTER=0 \
GZ_BENCH_CORE_LEDGER=1 \
GZ_BENCH_CORE_MD=2 \
GZ_BENCH_CORE_TD=3 \
GZ_BENCH_CORE_STRATEGY=4 \
GZ_BENCH_RUN_TIMEOUT_SEC=2 \
GZ_BENCH_ANALYSIS_SKIP_FIRST=100 \
GZ_BENCH_ANALYSIS_MAX_MESSAGES=10000 \
bash run.sh run-once-cpp
```

Outputs are written under `analysis/output` by default.

## Reported Statistics

The analyzer reports `count`, `min`, `max`, `mean`, `p50`, `p90`, `p99`, and `p99.9` for each latency metric. The main result should focus on percentiles rather than average latency.

For publishable results, use repeated runs and report run-to-run variability. A future `run-many-cpp` command should automate this.

## Limitations

Current limitations:

- v1 benchmark is godzilla-only; it is not a Hummingbot comparison.
- strategy logic is a minimal benchmark strategy, not a full production market-making strategy.
- depth to order-input matching is by `(symbol, side, price)` rather than a strict propagated event id.
- results are sensitive to OS scheduling, CPU topology, CPU governor, PM2 process placement, and machine load.
- journal timestamps measure the local software path only.
