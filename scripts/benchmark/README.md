## Installation Steps 

1.Instaill Miniconda

Switch to root and goto home directory
```bash
sudo su
cd ~
```
Update Dependencies
```bash
apt update && apt upgrade
```
Install 
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

The last choice

"Do you wish to update your shell profile to automatically initialize conda?"

Please input yes (default is no) and then activate
```bash
source ~/.bashrc
```

2.Update bashrc
```bash
nano ~/.bashrc
```
add those two lines in the end:
```bash
export LD_LIBRARY_PATH=~/dev/godzilla-community/core/build:~/dev/godzilla-community/core/python/extensions/mock
export PYTHONPATH=~/dev/godzilla-community/core/python/:~/dev/godzilla-community/core/python/extensions/mock:~/dev/godzilla-community/core/build
```
activate the change
```bash
source ~/.bashrc
```

3.Clone the repository
```bash
cd ~/dev/
git clone https://github.com/godzilla-foundation/godzilla-community.git
```

4.Pre Build
```bash
cd ~/dev/godzilla-community/scripts
bash pre_build.sh
```

5.Build
```bash
cd ~/dev/godzilla-community/core
mkdir build
cd build
cmake ..
make
```

6.Copy exchange extension
```bash
cd ~/dev/godzilla-community/core/extensions/
cp -rf mock/ ~/dev/godzilla-community/core/python/extensions/
```

7.Add user api_key and sec_key
```bash
cd ~/dev/godzilla-community
python core/python/dev_run.py account -s mock add
```
user_id : gz_user1
access_key : x
secret_key : x

8.Launch benchmark services
```bash
cd ~/dev/godzilla-community/scripts/benchmark/
bash run.sh start
```

You should see these 6 service instances:
```text
benchmark_replay_server
benchmark_master
benchmark_ledger
benchmark_md_mock
benchmark_td_mock:benchmark
benchmark_strategy
```

Check them with:
```bash
pm2 ls
```

Raw traces are written under:
```text
scripts/benchmark/traces/raw
```

9.Run analysis
```bash
cd ~/dev/godzilla-community/scripts/benchmark
python3 analysis/summarize_latency.py --raw-dir traces/raw --out-dir analysis/output
```

### Shm-only latency mode

To measure the Kungfu internal MD -> strategy -> TD path without the TCP replay server and without the mock exchange order socket:

```bash
bash run.sh stop
bash run.sh start-shm
python3 analysis/summarize_latency.py --raw-dir traces/raw --out-dir analysis/output
```

`start-shm` starts only master, ledger, mock MD, mock TD, and the benchmark strategy. Mock MD publishes Depth directly from the extension after the strategy subscribes. Mock TD records the incoming OrderInput and writes an order report without sending to the replay server. In this mode `mock_exchange_orders.csv` is not expected, and `exchange_unmatched` in the analysis output is expected to equal `joined_rows`.

`start-shm` defaults `GZ_BENCH_TRACE_MODE=buffered`: trace rows are queued in the hot path and flushed by a background writer, so `analysis/summarize_latency.py` can still read CSV output. Use `GZ_BENCH_TRACE_MODE=csv` for synchronous debug traces, or `GZ_BENCH_TRACE_MODE=journal`/`off` to disable benchmark CSV traces entirely.


### Native C++ benchmark

To run the native strategy variant, build `strategies/benchmark_cpp` and launch:

```bash
bash run.sh start-cpp
```

`start-cpp` uses the same benchmark wiring as `start-shm`, but loads the native pybind strategy module from `strategies/benchmark_cpp/build`.

For journal-only shm latency analysis, start with `GZ_BENCH_TRACE_MODE=journal` and summarize from Kungfu journals:

```bash
GZ_BENCH_TRACE_MODE=journal bash run.sh start-shm
python3 analysis/summarize_latency_journal.py --out-dir analysis/output
```

The default direct MD interval is 5ms to avoid Python strategy/CSV trace backlog. For throughput stress tests, override it explicitly:

```bash
GZ_MOCK_MD_INTERVAL_NS=1000000 bash run.sh start-shm
```

For the native journal-only benchmark path, the current recommended MD spin setting is `GZ_MOCK_MD_SPIN_NS=100000`, which gave the best 5-run tail behavior in our latest comparison on `GZ_MOCK_MD_INTERVAL_NS=300000`.

### One-shot native benchmark

Use `run-once-cpp` for repeatable native shm-only latency runs. It stops any existing benchmark services, clears journals/traces, starts the native C++ benchmark stack, waits for a short drain window, stops services, runs journal analysis, and prints the key latency summary.

Recommended command:

```bash
cd ~/dev/godzilla-community/scripts/benchmark

GZ_BENCH_TRACE_MODE=journal \
GZ_MOCK_MD_INTERVAL_NS=300000 \
GZ_MOCK_MD_MAX_EVENTS=5000 \
GZ_MOCK_MD_SPIN_NS=100000 \
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

Key controls:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GZ_BENCH_TRACE_MODE` | `buffered` | Use `journal` for journal-only latency analysis without benchmark CSV writes in the hot path. |
| `GZ_MOCK_MD_INTERVAL_NS` | `1000000` in `start-cpp` | Native mock MD publish interval in nanoseconds. `300000` means 300us. |
| `GZ_MOCK_MD_MAX_EVENTS` | `0` | Maximum native MD depth events to publish. `0` means unlimited. |
| `GZ_MOCK_MD_SPIN_NS` | `0` | Sleep+spin wait window for native MD. For example, `100000` sleeps until 100us before the next tick, then busy-spins. |
| `GZ_BENCH_CORE_MASTER` | unset | Optional CPU core list for master, applied with `taskset -pc`. |
| `GZ_BENCH_CORE_LEDGER` | unset | Optional CPU core list for ledger. |
| `GZ_BENCH_CORE_MD` | unset | Optional CPU core list for mock MD. |
| `GZ_BENCH_CORE_TD` | unset | Optional CPU core list for mock TD. |
| `GZ_BENCH_CORE_STRATEGY` | unset | Optional CPU core list for native strategy. |
| `GZ_BENCH_RUN_TIMEOUT_SEC` | `2` | Extra drain wait after `start-cpp` returns before stopping services. |
| `GZ_BENCH_ANALYSIS_SKIP_FIRST` | `100` | Number of joined rows to skip before summarizing, useful for removing startup warmup. |
| `GZ_BENCH_ANALYSIS_MAX_MESSAGES` | `10000` | Maximum journal frames to read per session during analysis. |
| `GZ_BENCH_ANALYSIS_OUT_DIR` | `analysis/output` | Analysis output directory. |

`run-once-cpp` prints the full analyzer output plus a compact summary like:

```text
summary_json: analysis/output/summary_journal.json
input_rows: {"depth":5000,"order":1000,"order_input":1000}
joined_rows: 900
join_counts: {"depth_price_side":1000,"depth_time":0,"depth_unmatched":0,"order_order_id":1000,"order_time":0,"order_unmatched":0}
total_tick_to_trade_ns: count=900 p50=136064.0ns p90=301849.6ns p99=464430.08ns p99.9=609928.192ns
```

The current journal analyzer joins TD reports by `order_id` and joins depth to order input by `(symbol, side, price)` first, with time matching as fallback. The joined CSV includes `depth_event_id`, `join_depth_method`, and `join_order_method` columns so each row's matching method can be audited.

### Multi-run native benchmark

Use `run-many-cpp` to repeat the one-shot native benchmark and aggregate run-to-run variability:

```bash
cd ~/dev/godzilla-community/scripts/benchmark

GZ_BENCH_RUNS=5 \
GZ_BENCH_ANALYSIS_OUT_DIR=analysis/output_many \
GZ_BENCH_TRACE_MODE=journal \
GZ_MOCK_MD_INTERVAL_NS=300000 \
GZ_MOCK_MD_MAX_EVENTS=5000 \
GZ_MOCK_MD_SPIN_NS=100000 \
GZ_BENCH_CORE_MASTER=0 \
GZ_BENCH_CORE_LEDGER=1 \
GZ_BENCH_CORE_MD=2 \
GZ_BENCH_CORE_TD=3 \
GZ_BENCH_CORE_STRATEGY=4 \
GZ_BENCH_RUN_TIMEOUT_SEC=2 \
GZ_BENCH_ANALYSIS_SKIP_FIRST=100 \
GZ_BENCH_ANALYSIS_MAX_MESSAGES=10000 \
bash run.sh run-many-cpp
```

Each run is written to `analysis/output_many/run_001`, `run_002`, and so on. The aggregate files are:

```text
analysis/output_many/runs_summary.csv
analysis/output_many/runs_summary.json
```

The aggregate summary reports min/mean/max across runs for `p50`, `p90`, `p99`, and `p99.9`, plus the best and worst run by `total_tick_to_trade_ns.p99_ns`.

### Journal latency charts

Generate publishable charts from one run:

```bash
python3 analysis/plot_journal_latency.py \
  --joined analysis/output/run_001/joined_latency_journal.csv \
  --out-dir analysis/output/run_001/charts
```

Generate charts from repeated runs:

```bash
python3 analysis/plot_journal_latency.py \
  --runs-dir analysis/output_many \
  --out-dir analysis/output_many/charts
```

Default chart outputs:

```text
total_tick_to_trade_ns_histogram.png
total_tick_to_trade_ns_cdf.png
total_tick_to_trade_ns_tail_by_run.png
stage_breakdown.png
total_tick_to_trade_ns_percentiles.csv
```

Use `--metric md_to_order_input_ns`, `--metric order_report_ns`, or `--metric total_tick_to_trade_ns` to plot a different metric. Use `--all-metrics` to generate histogram, CDF, tail-by-run, and percentile CSV files for all three metrics in one command:

```bash
python3 analysis/plot_journal_latency.py \
  --runs-dir analysis/output_many \
  --out-dir analysis/output_many/charts \
  --all-metrics
```

### Tail latency analysis

Export p99/p99.9 rows and the slowest rows from repeated journal runs:

```bash
python3 analysis/analyze_tail_latency.py \
  --runs-dir analysis/output_many \
  --out-dir analysis/output_many/tail
```

Default tail outputs:

```text
total_tick_to_trade_ns_p99_rows.csv
total_tick_to_trade_ns_p99.9_rows.csv
total_tick_to_trade_ns_top50.csv
total_tick_to_trade_ns_tail_summary.json
```

The tail summary reports threshold values, row counts, dominant stage counts, join method counts, run distribution, and stage means for each tail percentile. Use `--metric md_to_order_input_ns` or `--metric order_report_ns` to inspect a specific stage.

