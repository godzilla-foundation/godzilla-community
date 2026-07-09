#!/bin/bash

WORK_HOME=`dirname $0`


set_affinity() {
    app_name=$1
    core_list=$2

    if [ "$core_list" = "" ]; then
        return
    fi
    if ! command -v taskset >/dev/null 2>&1; then
        echo "taskset not found, skip cpu affinity for $app_name"
        return
    fi

    app_pid=`pm2 pid "$app_name" 2>/dev/null | tail -n 1`
    if [ "$app_pid" = "" ] || [ "$app_pid" = "0" ]; then
        echo "failed to get pid for $app_name, skip cpu affinity"
        return
    fi

    taskset -pc "$core_list" "$app_pid" >/dev/null
    if [ $? -eq 0 ]; then
        echo "set cpu affinity $app_name pid=$app_pid cores=$core_list"
    else
        echo "failed to set cpu affinity $app_name pid=$app_pid cores=$core_list"
    fi
}

prepare() {
    cd $WORK_HOME

    echo "clearing journal..."
    find ~/.config/kungfu/app/ -name "*.journal" | xargs rm -f

    echo "clearing benchmark traces..."
    mkdir -p traces/raw
    rm -f traces/raw/*.csv
}

start() {
    prepare

    # start mock replay server
    pm2 start replay_server.json
    echo "starting benchmark replay server..."
    sleep 3

    # start master
    pm2 start master.json
    set_affinity benchmark_master "$GZ_BENCH_CORE_MASTER"
    echo "starting master..."
    sleep 5

    # start ledger
    pm2 start ledger.json
    set_affinity benchmark_ledger "$GZ_BENCH_CORE_LEDGER"
    echo "starting ledger..."
    sleep 5

    # start mock md
    pm2 start md_mock.json
    set_affinity benchmark_md_mock "$GZ_BENCH_CORE_MD"
    echo "starting mock md..."
    sleep 5

    # start mock td
    pm2 start td_mock.json
    set_affinity 'benchmark_td_mock:benchmark' "$GZ_BENCH_CORE_TD"
    echo "starting mock td..."
    sleep 5

    # start benchmark strategy
    pm2 start strategy.json
    set_affinity benchmark_strategy "$GZ_BENCH_CORE_STRATEGY"
    echo "starting benchmark strategy..."
    sleep 5

    echo "pm2 ls to show the services"
}

start_shm() {
    prepare

    # start master
    pm2 start master.json
    set_affinity benchmark_master "$GZ_BENCH_CORE_MASTER"
    echo "starting master..."
    sleep 5

    # start ledger
    pm2 start ledger.json
    set_affinity benchmark_ledger "$GZ_BENCH_CORE_LEDGER"
    echo "starting ledger..."
    sleep 5

    TRACE_MODE=${GZ_BENCH_TRACE_MODE:-buffered}

    # start mock md in direct shm mode
    GZ_BENCH_TRACE_MODE=$TRACE_MODE GZ_MOCK_MD_DIRECT=1 GZ_MOCK_MD_INTERVAL_NS=${GZ_MOCK_MD_INTERVAL_NS:-5000000} pm2 start md_mock.json --update-env
    set_affinity benchmark_md_mock "$GZ_BENCH_CORE_MD"
    echo "starting mock md direct shm mode..."
    sleep 5

    # start mock td without exchange socket
    GZ_BENCH_TRACE_MODE=$TRACE_MODE GZ_MOCK_TD_NO_SOCKET=1 GZ_MOCK_TD_NATIVE=${GZ_MOCK_TD_NATIVE:-1} pm2 start td_mock.json --update-env
    set_affinity 'benchmark_td_mock:benchmark' "$GZ_BENCH_CORE_TD"
    echo "starting mock td no-socket mode..."
    sleep 5

    # start benchmark strategy
    GZ_BENCH_TRACE_MODE=$TRACE_MODE pm2 start strategy.json --update-env
    set_affinity benchmark_strategy "$GZ_BENCH_CORE_STRATEGY"
    echo "starting benchmark strategy..."
    sleep 5

    echo "pm2 ls to show the services"
}

start_cpp() {
    prepare

    # start master
    pm2 start master.json
    set_affinity benchmark_master "$GZ_BENCH_CORE_MASTER"
    echo "starting master..."
    sleep 5

    # start ledger
    pm2 start ledger.json
    set_affinity benchmark_ledger "$GZ_BENCH_CORE_LEDGER"
    echo "starting ledger..."
    sleep 5

    TRACE_MODE=${GZ_BENCH_TRACE_MODE:-buffered}

    # start mock md in direct shm mode
    GZ_BENCH_TRACE_MODE=$TRACE_MODE GZ_MOCK_MD_NATIVE=${GZ_MOCK_MD_NATIVE:-1} GZ_MOCK_MD_DIRECT=1 GZ_MOCK_MD_INTERVAL_NS=${GZ_MOCK_MD_INTERVAL_NS:-1000000} GZ_MOCK_MD_MAX_BATCH=${GZ_MOCK_MD_MAX_BATCH:-1} GZ_MOCK_MD_MAX_EVENTS=${GZ_MOCK_MD_MAX_EVENTS:-0} GZ_MOCK_MD_SPIN_NS=${GZ_MOCK_MD_SPIN_NS:-0} pm2 start md_mock.json --update-env
    set_affinity benchmark_md_mock "$GZ_BENCH_CORE_MD"
    echo "starting mock md direct shm mode..."
    sleep 5

    # start mock td without exchange socket
    GZ_BENCH_TRACE_MODE=$TRACE_MODE GZ_MOCK_TD_NO_SOCKET=1 GZ_MOCK_TD_NATIVE=${GZ_MOCK_TD_NATIVE:-1} pm2 start td_mock.json --update-env
    set_affinity 'benchmark_td_mock:benchmark' "$GZ_BENCH_CORE_TD"
    echo "starting mock td no-socket mode..."
    sleep 5

    # start native benchmark strategy
    GZ_BENCH_TRACE_MODE=$TRACE_MODE pm2 start strategy_cpp.json --update-env
    set_affinity benchmark_strategy_cpp "$GZ_BENCH_CORE_STRATEGY"
    echo "starting native benchmark strategy..."
    sleep 5

    echo "pm2 ls to show the services"
}

print_summary() {
    summary_path=$1

    if [ ! -f "$summary_path" ]; then
        echo "summary not found: $summary_path"
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -r '
            "summary_json: " + input_filename,
            "input_rows: " + (.metadata.input_rows | tostring),
            "joined_rows: " + (.metadata.joined_rows | tostring),
            "join_counts: " + (.metadata.join_counts | tostring),
            "total_tick_to_trade_ns: count=" + (.metrics.total_tick_to_trade_ns.count | tostring)
                + " p50=" + (.metrics.total_tick_to_trade_ns.p50_ns | tostring) + "ns"
                + " p90=" + (.metrics.total_tick_to_trade_ns.p90_ns | tostring) + "ns"
                + " p99=" + (.metrics.total_tick_to_trade_ns.p99_ns | tostring) + "ns"
                + " p99.9=" + (.metrics.total_tick_to_trade_ns.p99_9_ns | tostring) + "ns"
        ' "$summary_path"
    else
        python3 - "$summary_path" <<'PY_SUMMARY'
import json
import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
metric = data["metrics"]["total_tick_to_trade_ns"]
print(f"summary_json: {path}")
print(f"input_rows: {data['metadata']['input_rows']}")
print(f"joined_rows: {data['metadata']['joined_rows']}")
print(f"join_counts: {data['metadata']['join_counts']}")
print(
    "total_tick_to_trade_ns: "
    f"count={metric['count']} "
    f"p50={metric['p50_ns']}ns "
    f"p90={metric['p90_ns']}ns "
    f"p99={metric['p99_ns']}ns "
    f"p99.9={metric['p99_9_ns']}ns"
)
PY_SUMMARY
    fi
}

run_once_cpp() {
    cd $WORK_HOME

    out_dir=${GZ_BENCH_ANALYSIS_OUT_DIR:-analysis/output}
    wait_sec=${GZ_BENCH_RUN_TIMEOUT_SEC:-2}
    skip_first=${GZ_BENCH_ANALYSIS_SKIP_FIRST:-100}
    max_messages=${GZ_BENCH_ANALYSIS_MAX_MESSAGES:-10000}

    echo "stopping existing benchmark services..."
    stop

    echo "starting one-shot native benchmark..."
    start_cpp

    echo "waiting ${wait_sec}s for benchmark drain..."
    sleep $wait_sec

    echo "stopping benchmark services..."
    stop

    echo "analyzing journals..."
    GZ_JOURNAL_MAX_MESSAGES=$max_messages python3 analysis/summarize_latency_journal.py --out-dir "$out_dir" --skip-first "$skip_first" --max-messages "$max_messages"
    print_summary "$out_dir/summary_journal.json"
}

stop() {
    cd $WORK_HOME

    pm2 delete benchmark_strategy 2>/dev/null
    pm2 delete benchmark_strategy_cpp 2>/dev/null
    pm2 delete benchmark_td_mock:benchmark 2>/dev/null
    pm2 delete benchmark_md_mock 2>/dev/null
    pm2 delete benchmark_ledger 2>/dev/null
    pm2 delete benchmark_master 2>/dev/null
    pm2 delete benchmark_replay_server 2>/dev/null

    master_pid=`ps -ef | grep python | grep master | awk '{ print $2 }'`
    if [ "$master_pid" != "" ]; then
        kill -2 $master_pid
    fi
}


if [ $# -lt 1 ]; then
    echo "please indicate action [start/start-shm/start-cpp/run-once-cpp/stop]"
    exit 1
fi
if [ "$1" = "start" ]; then
    start
elif [ "$1" = "start-shm" ]; then
    start_shm
elif [ "$1" = "start-cpp" ]; then
    start_cpp
elif [ "$1" = "run-once-cpp" ]; then
    run_once_cpp
elif [ "$1" = "stop" ]; then
    stop
else
    echo "invalid action: $1"
fi
