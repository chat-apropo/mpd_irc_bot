################################################################################
#      ____  ___    ____  ________     ____  ____  ______
#     / __ \/   |  / __ \/  _/ __ \   / __ )/ __ \/_  __/
#    / /_/ / /| | / / / // // / / /  / __  / / / / / /
#   / _, _/ ___ |/ /_/ // // /_/ /  / /_/ / /_/ / / /
#  /_/ |_/_/  |_/_____/___/\____/  /_____/\____/ /_/
#
#
# Matheus Fillipe 18/05/2022
# MIT License
################################################################################


import asyncio
import os
import stat
from typing import Callable

import trio

BUFFER_SIZE = 1024


async def listen_loop(fifo_path: str, handler: Callable):
    if os.path.exists(fifo_path):
        os.remove(fifo_path)

    os.mkfifo(fifo_path)
    os.chmod(fifo_path, stat.S_IRWXO | stat.S_IRWXU | stat.S_IRWXG)
    print("Message Relay listening at fifo: " + fifo_path)
    while True:
        async with await trio.open_file(fifo_path) as fifo:
            async for line in fifo:
                line = line.strip()
                if asyncio.iscoroutinefunction(handler):
                    await handler(line)
                else:
                    handler(line)

if __name__ == "__main__":
    trio.run(listen_loop, "/tmp/fifo", print)
