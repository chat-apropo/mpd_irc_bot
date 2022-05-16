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

import datetime
import logging
import os
import re
import threading
from pathlib import Path
from functools import wraps

import trio
import validators
from typing import Union, List
from cachetools import TTLCache
from IrcBot.bot import Color, IrcBot, Message, utils
from IrcBot.dcc import DccServer
from IrcBot.utils import debug, log

# import all excetions
from audio_download import (ExtensionNotAllowed, FailedToDownload,
                            FailedToProcess, MaxAudioLength, MaxFilesize,
                            download_audio)
from message_server import listen_loop
from mpd_client import MPDClient, mpd_loop_with_handler

LOGFILE = None
LOG_LEVEL = logging.DEBUG
ADMINS = ["mattf", "gasconheart"]
HOST = 'irc.dot.org.es'
PORT = 6697
NICK = '_mpdbot'
PASSWORD = ''
CHANNELS = ["#bots"]
DCC_HOST = "127.0.0.1"
MUSIC_DIR = "~/music/mpdbot"
ICECAST_CONFIG = "/etc/icecast.xml"
MESSAGE_RELAY_FIFO_PATH = "/tmp/mpdbot_relay.sock"
MPD_HOST = "localhost"
MPD_PORT = 6600
MPD_FOLDER = "~/music/"
MAX_USER_QUEUE_LENGTH = 3
PREFIX = "!"


utils.setPrefix(PREFIX)

logger = utils.logger

mpd_client = MPDClient(MPD_HOST, MPD_PORT)

nick_cache = {}


def auth_command(*m_args, **m_kwargs):
    def wrap_cmd(func):
        @utils.arg_command(*m_args, **m_kwargs)
        async def wrapped(bot: IrcBot, args: re.Match, msg: Message):
            if not await is_identified(bot, msg.nick):
                await reply(bot, msg, "You cannot use this bot before you register your nick")
                return
            return await func(bot, args, msg)
        return wrapped
    return wrap_cmd

def admin_command(*m_args, **m_kwargs):
    def wrap_cmd(func):
        @utils.arg_command(*m_args, **m_kwargs)
        async def wrapped(bot: IrcBot, args: re.Match, msg: Message):
            if not await is_identified(bot, msg.nick):
                await reply(bot, msg, "You cannot use this bot before you register your nick")
                return
            if msg.nick not in ADMINS:
                await reply(bot, msg, "Only admins can use this command")
                return
            return await func(bot, args, msg)
        return wrapped
    return wrap_cmd

def non_numeric_arg(args: re.Match, i: int):
    return not args or not args.group(i) or not args.group(i).isdigit()

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

async def is_identified(bot: IrcBot, nick: str) -> bool:
    global nick_cache
    nickserv = "NickServ"
    if nick in nick_cache and "status" in nick_cache[nick]:
        msg = nick_cache[nick]["status"]
    else:
        await bot.send_message(f"status {nick}", nickserv)
        # We need filter because multiple notices from nickserv can come at the same time
        # if multiple requests are being made to this function all together
        msg = await bot.wait_for(
            "notice",
            nickserv,
            timeout=5,
            cache_ttl=15,
            filter_func=lambda m: nick in m["text"],
        )
        nick_cache[nick] = TTLCache(128, 10)
        nick_cache[nick]["status"] = msg
    return msg.get("text").strip() == f"{nick} 3 {nick}" if msg else False

def _reply_str(bot: IrcBot, in_msg: Message, text: str):
    return f"({in_msg.nick}): {text}"

async def reply(bot: IrcBot, in_msg: Message, message: Union[str, List[str]]):
    """Reply to a message."""
    if isinstance(message, str):
        message = [message]
    for text in message:
        msg = _reply_str(bot, in_msg, text)
        await bot.send_message(msg, channel=in_msg.channel)

def sync_write_fifo(text):
    with open(MESSAGE_RELAY_FIFO_PATH, "w") as f:
        f.write(text)

def download_in_thread(bot: IrcBot, in_msg: Message, url: str):
    """Download a file in a thread."""

    # TODO make this a limited request thread pool
    def download_in_thread_target(song_url: str):
        err = None
        try:
            song = download_audio(song_url, os.path.join(MPD_FOLDER, NICK))
        except MaxFilesize as e:
            err = f"That file is too big. {e}"
        except MaxAudioLength as e:
            err = f"That audio is too long. {e}"
        except FailedToProcess:
            err = "That audio could not be processed"
        except FailedToDownload:
            err = "That audio could not be downloaded"
        except ExtensionNotAllowed as e:
            err = f"That audio extension is not allowed. {e}"
        except Exception as e:
            err = f"Error: {e}"
        if err:
            err = _reply_str(bot, in_msg, err)
            sync_write_fifo(f"[[{in_msg.channel}]] {err}")
            return

        uri = os.path.join(NICK, Path(song).name)
        logger.debug(f"Adding '{uri=}' to the playlist")
        mpd_client.add_next(uri)
        onend_text = _reply_str(bot, in_msg, f"{Path(song).stem} has been added to the playlist")
        sync_write_fifo(f"[[{in_msg.channel}]] {onend_text}")

    threading.Thread(
        target=download_in_thread_target,
        args=(url,),
        daemon=True,
    ).start()


@auth_command("status", "Info about the current song and player status")
async def status(bot: IrcBot, args: re.Match, msg: Message):
    song = mpd_client.current_song()
    await reply(bot, msg, song)

@auth_command("list", "Shows next songs in queue")
async def list(bot: IrcBot, args: re.Match, msg: Message):
    await reply(bot, msg, mpd_client.next_songs())

@auth_command("fulllist", "Shows all the songs in the playlist", "You will receive a DM from the bot")
async def fullist(bot: IrcBot, args: re.Match, msg: Message):
    msg.channel = msg.nick
    await reply(bot, msg, mpd_client.playlist())

@auth_command("add", "Add a song to the playlist", f"{PREFIX}add <youtube_link|audio_url>. You can also submit audios with dcc. You cannot enqueue more than {MAX_USER_QUEUE_LENGTH} audios.")
async def add(bot: IrcBot, args: re.Match, msg: Message):
    args = utils.m2list(args)
    if len(args) == 0:
        await reply(bot, msg, "You need to specify a song to add")
        return

    if len(args) > 1:
        await reply(bot, msg, "You can only add one song at a time")
        return

    song_url = args[0]
    if not song_url.startswith("http"):
        await reply(bot, msg, "That is not a valid url: " + song_url)
        return

    await reply(bot, msg, "Downloading...")
    download_in_thread(bot, msg, song_url)


@utils.arg_command("source", "Shows bot source code url")
async def source(bot: IrcBot, args: re.Match, msg: Message):
    await reply(bot, msg, "https://github.com/matheusfillipe/mpd_irc_bot")

@admin_command("keep", "(ADMIN) keeps the music another use added", f"(ADMIN) {PREFIX}keep <nick> [number] -- if number is omitted will keep all songs added by a user")
async def keep(bot: IrcBot, args: re.Match, msg: Message):
    pass

@admin_command("next", "(ADMIN) Skips to next song in the playlist")
async def next(bot: IrcBot, args: re.Match, msg: Message):
    try:
        mpd_client.next()
    except Exception:
        await reply(bot, msg, "Could not go to next song")

@admin_command("prev", "(ADMIN) Goes back to previous song in the playlist")
async def previous(bot: IrcBot, args: re.Match, msg: Message):
    try:
        mpd_client.previous()
    except Exception:
        await reply(bot, msg, "Could not go back to previous song")

@admin_command("play", "(ADMIN) Play song in certain position", f"(ADMIN) {PREFIX}play <position>")
async def play(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1):
        await reply(bot, msg, "You need to specify a position")
        return
    try:
        mpd_client.play(args[1])
    except Exception:
        await reply(bot, msg, "Could not play song")

@admin_command("delete", "(ADMIN) Deletes a song in certain position", f"(ADMIN) {PREFIX}delete <position>")
async def delete(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1):
        await reply(bot, msg, "You need to specify a position")
        return
    try:
        mpd_client.delete(args[1])
    except Exception:
        await reply(bot, msg, "Failed to delete song")

@admin_command("move", "(ADMIN) Moves a song to a certain position", f"(ADMIN) {PREFIX}move <from> <to>")
async def move(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1) or non_numeric_arg(args, 2):
        await reply(bot, msg, "You need to specify a from position and a to position")
        return
    try:
        mpd_client.move(args[1], args[2])
    except Exception:
        await reply(bot, msg, "Failed to move!")


async def onconnect(bot: IrcBot):
    async def message_handler(text):
        match = re.match(r"^\[\[([^\]]+)\]\] (.*)$", text)
        if match:
            channel, text = match.groups()
            logging.debug(f" Message relay server handler regex: {channel=}, {text=}")
            await bot.send_message(text, channel)
            return
        for channel in CHANNELS:
            logging.debug(f" Message relay server handler simple: {channel=}, {text=}")
            await bot.send_message(text, channel)

    async def mpd_player_handler():
        await message_handler(f"Playing: {mpd_client.current_song_name()}")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(listen_loop, MESSAGE_RELAY_FIFO_PATH, message_handler)
        nursery.start_soon(mpd_loop_with_handler, mpd_player_handler)

utils.setHelpHeader("RADIO BOT COMMANDS")
utils.setHelpBottom("You can learn more about sonic pi at: https://sonic-pi.net/tutorial.html")

if __name__ == "__main__":
    utils.setLogging(LOG_LEVEL, LOGFILE)
    bot = IrcBot(HOST, PORT, NICK, CHANNELS, PASSWORD, use_ssl=PORT == 6697, dcc_host=DCC_HOST)
    bot.runWithCallback(onconnect)
