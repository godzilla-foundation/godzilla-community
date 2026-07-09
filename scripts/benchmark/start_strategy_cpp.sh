#!/bin/bash

set -e

WORK_HOME=`dirname $0`
ROOT_DIR=`cd "$WORK_HOME/../.." && pwd`

shopt -s nullglob
SO_FILES=("$ROOT_DIR/strategies/benchmark_cpp/build"/benchmark_cpp*.so)
shopt -u nullglob
if [ ${#SO_FILES[@]} -eq 0 ]; then
    echo "benchmark_cpp shared module not found under $ROOT_DIR/strategies/benchmark_cpp/build"
    exit 1
fi

STRATEGY_SO="${SO_FILES[0]}"
TRACE_MODE=${GZ_BENCH_TRACE_MODE:-buffered}

cd "$ROOT_DIR"
GZ_BENCH_TRACE_MODE=$TRACE_MODE python3 core/python/dev_run.py -l info strategy -g benchmark -n simple_benchmark_cpp -p "$STRATEGY_SO" -c strategies/benchmark_cpp/conf.json
