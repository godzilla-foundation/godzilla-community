#!/bin/bash

WORK_HOME=`dirname $0`

start() {
    cd $WORK_HOME

    echo "clearing journal..."
    find ~/.config/kungfu/app/ -name "*.journal" | xargs rm -f

    echo "clearing benchmark traces..."
    mkdir -p ../../core/extensions/mock/traces/raw
    rm -f ../../core/extensions/mock/traces/raw/*.csv

    # start mock replay server
    pm2 start replay_server.json
    echo "starting benchmark replay server..."
    sleep 3

    # start master
    pm2 start master.json
    echo "starting master..."
    sleep 5

    # start ledger
    pm2 start ledger.json
    echo "starting ledger..."
    sleep 5

    # start mock md
    pm2 start md_mock.json
    echo "starting mock md..."
    sleep 5

    # start mock td
    pm2 start td_mock.json
    echo "starting mock td..."
    sleep 5

    # start benchmark strategy
    pm2 start strategy.json
    echo "starting benchmark strategy..."
    sleep 5

    echo "pm2 ls to show the services"
}

stop() {
    cd $WORK_HOME

    pm2 delete benchmark_strategy 2>/dev/null
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
    echo "please indicate action [start/stop]"
    exit 1
fi
if [ "$1" = "start" ]; then
    start
elif [ "$1" = "stop" ]; then
    stop
else
    echo "invalid action: $1"
fi
