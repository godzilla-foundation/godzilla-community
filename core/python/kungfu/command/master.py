'''
This is source code modified under the Apache License 2.0.
Original Author: Keren Dong
Modifier: kx@godzilla.dev
Modification date: March 3, 2025
'''
import click
from kungfu.command import kfc, pass_ctx_from_parent
from kungfu.practice.master import Master


@kfc.command(help_priority=1)
@click.option('-x', '--low_latency', is_flag=True, help='run in low latency mode')
@click.pass_context
def master(ctx, low_latency):
    pass_ctx_from_parent(ctx)
    ctx.low_latency = low_latency
    server = Master(ctx)
    server.run()

