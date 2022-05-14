"""im going to make a bot that will let you input a youtube link, audio url, or
send an audio with dcc and it will add it as the next on the queue, each use
can like have 3 audios at once on the queue unless admins.

It will also let you play live with a sonic pi ruby repl. Also will
create passwords for authorized users to use the openmic
"""

# TODO download videos from youtube
# TODO edit icecast password for a source randomly
# TODO add to playlist, limit users queue length
# TODO accept mp3 files from dcc
# TODO accept youtube or audio links
# TODO irc bot commands

# https://github.com/matheusfillipe/ircbot/blob/main/examples/dccbot.py
# https://python-mpd2.readthedocs.io/en/latest/topics/getting-started.html 
# https://www.youtube.com/watch?v=3rW7Vpep3II 

import logging
import os

import trio
from IrcBot.bot import Color, IrcBot, Message, utils
from IrcBot.dcc import DccServer
from IrcBot.utils import debug, log

from message_server import listen_loop
from mpd_client import MPDClient, loop_with_handler

LOGFILE = None
LEVEL = logging.DEBUG
HOST = 'irc.dot.org.es'
PORT = 6697
NICK = '_mpdbot'
PASSWORD = ''
CHANNELS = ["#bots"]
DCC_HOST = "127.0.0.1"
MUSIC_DIR = "~/music/mpdbot"
ICECAST_CONFIG = "/etc/icecast.xml"
MESSAGE_RELAY_PATH = "/tmp/mpdbot_relay.sock"
MPD_HOST = "localhost"
MPD_PORT = 6600



mpd_client = MPDClient(MPD_HOST, MPD_PORT)

@utils.custom_handler("dccsend")
async def on_dcc_send(bot: IrcBot, **m):
    nick = m["nick"]
    if not await is_identified(bot, nick):
        await bot.dcc_reject(DccServer.SEND, nick, m["filename"])
        await bot.send_message(
            "You cannot use this bot before you register your nick", nick
        )
        return

    notify_each_b = progress_curve(m["size"])

    config = Config.get(nick)

    async def progress_handler(p, message):
        if not config.display_progress:
            return
        percentile = int(p * 100)
        if percentile % notify_each_b == 0:
            await bot.send_message(message % percentile, m["nick"])

    folder = Folder(nick)
    if folder.size() + int(m["size"]) > int(Config.get(nick).quota) * 1048576:
        await bot.send_message(
            Message(
                m["nick"],
                message="Your quota has exceeded! Type 'info' to check, 'list' to see your files and 'delete [filename]' to free some space",
                is_private=True,
            )
        )
        return

    path = folder.download_path(m["filename"])
    await bot.dcc_get(
        str(path),
        m,
        progress_callback=lambda _, p: progress_handler(
            p, f"UPLOAD {Path(m['filename']).name} %s%%"
        ),
    )
    await bot.send_message(
        Message(
            m["nick"], message=f"{m['filename']} has been received!", is_private=True
        )
    )


@utils.custom_handler("dccreject")
def on_dcc_reject(**m):
    log(f"Rejected!!! {m=}")


@utils.arg_command("list")
def echo(args, message):
    return Color(" ".join(utils.m2list(args)), Color.random())

async def onconnect(bot: IrcBot):
    async def message_handler(message):
        for channel in CHANNELS:
            await bot.send_message(message, channel)

    async def mpd_player_handler():
        mpd_client.current_song()['file']
        await message_handler(f"Playing: {mpd_client.current_song()['file']}")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(listen_loop, MESSAGE_RELAY_PATH, message_handler)
        nursery.start_soon(loop_with_handler, mpd_player_handler)

if __name__ == "__main__":
    utils.setLogging(LEVEL, LOGFILE)
    bot = IrcBot(HOST, PORT, NICK, CHANNELS, PASSWORD, use_ssl=PORT == 6697, dcc_host=DCC_HOST)
    bot.runWithCallback(onconnect)
