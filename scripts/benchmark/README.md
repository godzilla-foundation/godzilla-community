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

For journal-only shm latency analysis, start with `GZ_BENCH_TRACE_MODE=journal` and summarize from Kungfu journals:

```bash
GZ_BENCH_TRACE_MODE=journal bash run.sh start-shm
python3 analysis/summarize_latency_journal.py --out-dir analysis/output
```

The default direct MD interval is 5ms to avoid Python strategy/CSV trace backlog. For throughput stress tests, override it explicitly:

```bash
GZ_MOCK_MD_INTERVAL_NS=1000000 bash run.sh start-shm
```
