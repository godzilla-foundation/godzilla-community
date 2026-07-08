# Mock Benchmark Trace Schema

All timestamps are monotonic nanoseconds. The headline metric is:

```text
total_tick_to_trade_ns = t_order_socket_write_ns - t_msg_received_ns
```

ACK timing is diagnostic only and must not be included in headline latency.

## Raw Files

Default raw trace directory is `core/extensions/mock/traces/raw` from the repository root.
When scripts run with `scripts/benchmark` as cwd, strategy traces may appear under `scripts/benchmark/core/extensions/mock/traces/raw`; the analysis scripts can read either path via `--raw-dir`.

| File | Producer | Required columns |
| --- | --- | --- |
| `mock_md.csv` | mock MD | `event_id,symbol,t_exchange_emit_ns,t_msg_received_ns,t_strategy_visible_ns,md_ingest_ns` |
| `simple_benchmark_strategy.csv` | benchmark strategy | `run_id,system,event_id,symbol,side,order_id,client_order_id,t_exchange_emit_ns,t_msg_received_ns,t_strategy_visible_ns,t_strategy_triggered_ns,t_order_constructed_ns,decision_ns` |
| `mock_td.csv` | mock TD | `event_id,client_order_id,symbol,side,price,qty,t_order_constructed_ns,t_order_socket_write_ns` |
| `mock_exchange_orders.csv` | replay server | `event_id,client_order_id,symbol,side,price,qty,t_order_socket_write_ns,t_order_received_ns,t_ack_ns` |

## Joined Output

`analysis/summarize_latency.py` writes `joined_latency.csv` with:

```text
run_id,system,event_id,client_order_id,symbol,side,
t_exchange_emit_ns,t_msg_received_ns,t_strategy_visible_ns,
t_strategy_triggered_ns,t_order_constructed_ns,t_order_socket_write_ns,
t_order_received_ns,t_ack_ns,
md_ingest_ns,decision_ns,order_egress_ns,total_tick_to_trade_ns
```

Derived fields:

```text
md_ingest_ns = t_strategy_visible_ns - t_msg_received_ns
decision_ns = t_order_constructed_ns - t_strategy_triggered_ns
order_egress_ns = t_order_socket_write_ns - t_order_constructed_ns
total_tick_to_trade_ns = t_order_socket_write_ns - t_msg_received_ns
```

Preferred join key is `client_order_id`. Fallbacks are `event_id + side`, then `event_id`; fallback join counts must be treated as lower confidence until event id propagation is fixed end to end.
