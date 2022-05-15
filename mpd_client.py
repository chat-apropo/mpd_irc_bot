import asyncio
import datetime
import logging
from pathlib import Path
from typing import Callable

import trio
from mpd import MPDClient as Client

logger = logging.getLogger()

def dropin(func):
    """Decorator that connects the client, executes the function and
    disconnects the client."""
    def wrapper(*args, **kwargs):
        MPDClient.connect()
        result = func(*args, **kwargs)
        MPDClient.disconnect()
        return result
    return wrapper


def format_data(data, k):
    if k in ["elapsed", "duration"]:
        return str(datetime.timedelta(seconds=float(data[k].split('.')[0])))
    if k == "file":
        return Path(data[k]).stem
    return data[k]

class MPDClient:
    client: Client = None
    _host: str = None
    _port: int = None

    def __init__(self, host, port):
        MPDClient._host = host
        MPDClient._port = port

    @classmethod
    def connect(cls):
        cls.client = Client()
        cls.client.connect(cls._host, cls._port)

    @classmethod
    def disconnect(cls):
        cls.client.close()
        cls.client.disconnect()

    @dropin
    def cmd(self, cmd: str):
        return getattr(MPDClient.client, cmd)()

    @dropin
    def current_song(self):
        data = {}
        filter_keys = ["state", "duration", "elapsed"]
        data.update({k: v for k, v in MPDClient.client.status().items() if k in filter_keys})
        include_keys = ["duration", "file", "pos"]
        data.update({k: v for k, v in MPDClient.client.currentsong().items() if k in include_keys})
        return ", ".join(f"{k}: {format_data(data, k)}" for k in data)


    @dropin
    def current_song_name(self):
        return format_data(MPDClient.client.currentsong(), "file")

    @dropin
    def playlist(self):
        return MPDClient.client.playlistinfo()

    @dropin
    def add_next(self, song: str):
        MPDClient.client.add(song)
        status = MPDClient.client.currentsong()
        pos = int(status["pos"])
        status = MPDClient.client.status()
        length = int(status["playlistlength"])
        MPDClient.client.move(length - 1, pos + 1)

    async def wait_for_event(self, event="player"):
        stream = await trio.open_tcp_stream(MPDClient._host, MPDClient._port)
        async with stream:
            while True:
                response = await stream.receive_some(4096)
                response = response.decode().strip()
                if "OK MPD" in response:
                    await stream.send_all(f"idle {event}\n".encode())
                elif response.startswith("changed: "):
                    return response.split(" ")[1]

async def mpd_loop_with_handler(handler: Callable, event: str = "player"):
    c = MPDClient('localhost', 6600)
    while True:
        if await c.wait_for_event(event):
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()
        await trio.sleep(0)


async def main():
    c = MPDClient('localhost', 6600)
    print(c.current_song())
    await mpd_loop_with_handler(lambda: print(c.current_song_name()))

if __name__ == "__main__":
    trio.run(main)
