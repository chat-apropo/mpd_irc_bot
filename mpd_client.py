import logging

import trio
import asyncio
from mpd import MPDClient as Client
from typing import Callable

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

class MPDClient:
    client = None
    _host = None
    _port = None

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
    def current_song(self):
        return MPDClient.client.currentsong()

    @dropin
    def playlist(self):
        return MPDClient.client.playlistinfo()

    @dropin
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

async def loop_with_handler(handler: Callable, event: str = "player"):
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
    await loop_with_handler(lambda: print(c.current_song()['file']))

if __name__ == "__main__":
    trio.run(main)
