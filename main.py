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

# TODO edit icecast password for a source randomly

import datetime
import logging
import os
import re
from pathlib import Path
from typing import List, Union

import requests
import trio
from cachetools import TTLCache
from IrcBot.bot import Color, IrcBot, Message, utils
from IrcBot.dcc import DccServer
from slugify import slugify

# import all excetions
from audio_download import (MAX_AUDIO_LENGTH, MAX_FILE_SIZE,
                            ExtensionNotAllowed, FailedToDownload,
                            FailedToProcess, MaxAudioLength, MaxFilesize,
                            allowed_file, download_audio, get_audio_length)
from message_server import listen_loop
from mpd_client import MPDClient, mpd_loop_with_handler
from parseconf import config
from playlistmng import SongQueue, ThreadPool
from sonic_pi import Server as PiServer

LOGFILE = config["log"]["LOGFILE"]
if LOGFILE == "None":
    LOGFILE = None
LOG_LEVEL = config["log"]["LOG_LEVEL"]
ADMINS = config["bot"]["ADMINS"]
HOST = config["irc"]["HOST"]
PORT = config["irc"]["PORT"]
NICK = config["irc"]["NICK"]
PASSWORD = config["irc"]["PASSWORD"]
CHANNELS = config["irc"]["CHANNELS"]
DCC_HOST = config["irc"]["DCC_HOST"]
DCC_ANNOUNCE_HOST = config["irc"]["DCC_ANNOUNCE_HOST"]
DCC_PORTS = config["irc"]["DCC_PORTS"]
ICECAST_CONFIG = config["bot"]["ICECAST_CONFIG"]
MESSAGE_RELAY_FIFO_PATH = config["bot"]["MESSAGE_RELAY_FIFO_PATH"]
MPD_HOST = config["mpd"]["MPD_HOST"]
MPD_PORT = config["mpd"]["MPD_PORT"]
MPD_FOLDER = config["mpd"]["MPD_FOLDER"]
MAX_USER_QUEUE_LENGTH = config["mpd"]["MAX_USER_QUEUE_LENGTH"]
MAX_DOWNLOAD_THREADS = config["download"]["MAX_DOWNLOAD_THREADS"]
SONIC_PI_HOST = config["sonic-pi"]["SONIC_PI_HOST"]
SONIC_PI_PORT = config["sonic-pi"]["SONIC_PI_PORT"]
SONIC_PI_LIVE_URL = config["sonic-pi"]["SONIC_PI_LIVE_URL"]
PREFIX = config["bot"]["PREFIX"]


utils.setPrefix(PREFIX)

logger = utils.logger
mpd_client = MPDClient(MPD_HOST, MPD_PORT)
nick_cache = {}
song_queue = SongQueue(MAX_USER_QUEUE_LENGTH, mpd_client)
thread_pool = ThreadPool(4)
server = PiServer(SONIC_PI_HOST, SONIC_PI_PORT, None, None, True)
sonic_pi_users = {}


def paste(text):
    """Paste text to ix.io."""
    url = "http://ix.io"
    payload = {'f:1=<-': text}
    response = requests.request("POST", url, data=payload)
    return response.text


def read_paste(url):
    """Read text from ix.io."""
    response = requests.request("GET", url)
    return response.text


def auth_command(*m_args, **m_kwargs):
    def wrap_cmd(func):
        @utils.arg_command(*m_args, **m_kwargs)
        async def wrapped(bot: IrcBot, args: re.Match, msg: Message):
            if not await is_identified(bot, msg.nick):
                await reply(bot, msg, error("You cannot use this bot before you register your nick"))
                return
            return await func(bot, args, msg)
        return wrapped
    return wrap_cmd


def admin_command(*m_args, **m_kwargs):
    def wrap_cmd(func):
        @utils.arg_command(*m_args, **m_kwargs)
        async def wrapped(bot: IrcBot, args: re.Match, msg: Message):
            if not await is_identified(bot, msg.nick):
                await reply(bot, msg, error("You cannot use this bot before you register your nick"))
                return
            if msg.nick not in ADMINS:
                await reply(bot, msg, error("Only admins can use this command"))
                return
            return await func(bot, args, msg)
        return wrapped
    return wrap_cmd


def non_numeric_arg(args: re.Match, i: int):
    return not args or not args.group(i) or not args.group(i).isdigit()


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
    return f"{Color('(' + in_msg.nick + '):', fg=Color.green).str} {text}"


def error(text: str):
    return Color(text, fg=Color.red).str


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

    def download_in_thread_target(song_url: str):
        err = None
        try:
            song = download_audio(song_url, os.path.join(MPD_FOLDER, NICK))
        except MaxFilesize as e:
            err = error(f"That file is too big. {e}")
        except MaxAudioLength as e:
            err = error(f"That audio is too long. {e}")
        except FailedToProcess:
            err = error("That audio could not be processed")
        except FailedToDownload:
            err = error("That audio could not be downloaded")
        except ExtensionNotAllowed as e:
            err = error(f"That audio extension is not allowed. {e}")
        except Exception as e:
            err = error("Sorry but an error occurred.")
            logger.error(e)
        if err:
            err = _reply_str(bot, in_msg, err)
            sync_write_fifo(f"[[{in_msg.channel}]] {err}")
            return

        uri = os.path.join(NICK, Path(song).name)
        logger.debug(f"Adding '{uri=}' to the playlist")
        onend_text = _reply_str(
            bot, in_msg, f"{Path(song).stem} has been added to the playlist")
        if in_msg.nick in ADMINS:
            pos = song_queue.next_pos()
            try:
                mpd_client.add_at_pos(uri, pos)
                song_queue.last_pos = pos
            except Exception:
                onend_text = _reply_str(bot, in_msg, error("Sorry but an error occurred."))
        else:
            try:
                song_queue.add_song(in_msg.nick, uri)
            except SongQueue.FullUserError:
                onend_text = _reply_str(
                    bot, in_msg, error("Sorry but your queue is full. Wait until one of your songs finishes and try adding again."))
            except Exception:
                onend_text = _reply_str(bot, in_msg, error("Sorry but an error occurred."))

        sync_write_fifo(f"[[{in_msg.channel}]] {onend_text}")

    thread_pool.add_task(download_in_thread_target, url)


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
        await reply(bot, msg, error("You need to specify a song to add"))
        return

    if len(args) > 1:
        await reply(bot, msg, error("You can only add one song at a time"))
        return

    song_url = args[0]
    if not song_url.startswith("http"):
        await reply(bot, msg, error("That is not a valid url: ") + song_url)
        return

    nick = msg.nick
    if not song_queue.can_add(nick):
        await bot.send_message(
            f"You cannot add more than {MAX_USER_QUEUE_LENGTH} audios. Wait for one of your songs to finish and try again.",
            nick,
        )
        return

    try:
        download_in_thread(bot, msg, song_url)
        await reply(bot, msg, "Downloading...")
    except ThreadPool.FullError:
        await reply(bot, msg, error("The bot is currently busy downloading other songs. Try again soon."))


@auth_command("grab", "Grab the mic! Get an icecast password to start streaming", f"{PREFIX}grab - A password will be generated and you will get all the info as a dm.")
async def grab(bot: IrcBot, args: re.Match, msg: Message):
    # TODO Do icecast stuff
    pass


@auth_command("pi", "Toggles sonic pi repl", f"{PREFIX}pi [command]- https://sonic-pi.net/tutorial.html")
async def pi(bot: IrcBot, args: re.Match, msg: Message):
    args = utils.m2list(args)
    if args:
        sonic_pi_users[msg.nick] = [" ".join(args)]

    if msg.nick in sonic_pi_users:
        await reply(bot, msg, "Your Sonic Pi repl is now off. Sending code to sonic pi...")
        server.run_code("\n".join(sonic_pi_users[msg.nick]))
        return
    sonic_pi_users[msg.nick] = []
    await reply(bot, msg, f"Your Sonic Pi repl is now live at: {SONIC_PI_LIVE_URL}. Type {PREFIX}pi to turn it off and evaluate your code.")

@auth_command("pstop", "Stops sonice pi audio")
async def stop(bot: IrcBot, args: re.Match, msg: Message):
    server.stop_all_jobs()
    await reply(bot, msg, "Stopping audio...")

@auth_command("paste", "Pastes your sonic pi code")
async def pipaste(bot: IrcBot, args: re.Match, msg: Message):
    if msg.nick not in sonic_pi_users:
        await reply(bot, msg, error("You need to turn on your sonic pi repl first. Use {}pi".format(PREFIX)))
        return
    await reply(bot, msg, paste(sonic_pi_users[msg.nick]))


@auth_command("read", "Read code from ix.io paste (or any raw text url)")
async def readurl(bot: IrcBot, args: re.Match, msg: Message):
    try:
        server.run_code(read_paste(args[1]))
    except Exception as e:
        await reply(bot, msg, error("Failed to read paste: ") + str(e))
    await reply(bot, msg, "Code has been read and sent!")

@utils.arg_command("source", "Shows bot source code url")
async def source(bot: IrcBot, args: re.Match, msg: Message):
    await reply(bot, msg, "https://github.com/matheusfillipe/mpd_irc_bot")


@admin_command("keep", "(ADMIN) keeps the music another use added", f"(ADMIN) {PREFIX}keep <nick|pos> You can either specify a position of an individual song or a nick to keep all from")
async def keep(bot: IrcBot, args: re.Match, msg: Message):
    args = utils.m2list(args)
    if len(args) == 0:
        await reply(bot, msg, error("You need to specify a user"))
        return

    nick_or_pos = args[0]
    if nick_or_pos.isdigit():
        pos = int(nick_or_pos)
        if pos < 0 or pos >= len(song_queue.queue):
            await reply(bot, msg, error("That is not a valid position"))
            return
        try:
            song_queue.keep_song(pos)
        except SongQueue.PositionNotFoundError:
            await reply(bot, msg, error("That is not a valid position that was added by a user so it wont be deleted."))
            return
        return

    else:
        try:
            song_queue.keep_all(nick_or_pos)
        except KeyError:
            await reply(bot, msg, error("That user Did not add any songs"))
            return

    await reply(bot, msg, "song(s) have been kept")


@admin_command("next", "(ADMIN) Skips to next song in the playlist")
async def next(bot: IrcBot, args: re.Match, msg: Message):
    try:
        mpd_client.next()
    except Exception:
        await reply(bot, msg, error("Could not go to next song"))


@admin_command("prev", "(ADMIN) Goes back to previous song in the playlist")
async def previous(bot: IrcBot, args: re.Match, msg: Message):
    try:
        mpd_client.previous()
    except Exception:
        await reply(bot, msg, error("Could not go back to previous song"))


@admin_command("play", "(ADMIN) Play song in certain position", f"(ADMIN) {PREFIX}play <position>")
async def play(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1):
        await reply(bot, msg, error("You need to specify a position"))
        return
    try:
        mpd_client.play(args[1])
    except Exception:
        await reply(bot, msg, error("Could not play song"))


@admin_command("delete", "(ADMIN) Deletes a song in certain position", f"(ADMIN) {PREFIX}delete <position>")
async def delete(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1):
        await reply(bot, msg, "You need to specify a position")
        return
    try:
        mpd_client.delete(args[1])
        await reply(bot, msg, "Song deleted successfully")
    except Exception:
        await reply(bot, msg, error("Failed to delete song"))


@admin_command("move", "(ADMIN) Moves a song to a certain position", f"(ADMIN) {PREFIX}move <from> <to>")
async def move(bot: IrcBot, args: re.Match, msg: Message):
    if non_numeric_arg(args, 1) or non_numeric_arg(args, 2):
        await reply(bot, msg, "You need to specify a from position and a to position")
        return
    try:
        mpd_client.move(args[1], args[2])
        await reply(bot, msg, "Moved song successfully")
    except Exception:
        await reply(bot, msg, error("Failed to move!"))


@utils.custom_handler("dccsend")
async def on_dcc_send(bot: IrcBot, **m):
    nick = m["nick"]
    if not await is_identified(bot, nick):
        await bot.dcc_reject(DccServer.SEND, nick, m["filename"])
        await bot.send_message(
            error("You cannot use this bot before you register your nick"),
            nick
        )
        return

    if not song_queue.can_add(nick):
        await bot.dcc_reject(DccServer.SEND, nick, m["filename"])
        await bot.send_message(
            f"You cannot add more than {MAX_USER_QUEUE_LENGTH} audios. Wait for one of your songs to finish and try again.",
            nick,
        )
        return

    def progress_curve(filesize):
        notify_each_b = min(10, max(1, 10 - 10 * filesize // 1024 ** 3))
        return min([1, 2, 5, 10], key=lambda x: abs(x - notify_each_b))

    notify_each_b = progress_curve(m["size"])

    async def progress_handler(p, message):
        percentile = int(p * 100)
        if percentile % notify_each_b == 0:
            await bot.send_message(message % percentile, m["nick"])

    if int(m["size"]) > MAX_FILE_SIZE:
        await bot.send_message(
            error(
                f"File too big! Max file size is {MAX_FILE_SIZE} bytes"), m["nick"]
        )
        await bot.dcc_reject(DccServer.SEND, nick, m["filename"])
        return

    if not allowed_file(m["filename"]):
        await bot.send_message(
            error("File extension not allowed!"),
            m["nick"],
        )
        await bot.dcc_reject(DccServer.SEND, nick, m["filename"])
        return

    file = Path(m['filename'])
    to_dir = Path(MPD_FOLDER).expanduser() / Path(NICK)
    if not to_dir.exists():
        to_dir.mkdir(parents=True)
    path = to_dir / Path(slugify(file.stem) + file.suffix)
    if not await bot.dcc_get(
            str(path),
            m,
            progress_callback=lambda _, p: progress_handler(
                p, f"UPLOAD {Path(m['filename']).name} %s%%"
            ),):
        await bot.send_message(
            error("Failed to download file"), m["nick"]
        )
        return

    await bot.send_message(
        Message(
            m["nick"], message=f"{m['filename']} has been received!", is_private=True
        )
    )

    def on_add():
        uri = os.path.join(NICK, path.name)
        if get_audio_length(str(path)) > MAX_AUDIO_LENGTH:
            os.remove(str(path))
            sync_write_fifo(
                f"[[{m['nick']}]] Your audio is too lenghty. Max allowed is: {MAX_AUDIO_LENGTH} seconds.")
            return

        mpd_client.add_next(uri)
        onend_text = f"{m['filename']} has been added to the playlist!"
        if m['nick'] in ADMINS:
            pos = song_queue.next_pos()
            try:
                mpd_client.add_at_pos(uri, pos)
                song_queue.last_pos = pos
            except Exception:
                onend_text = error("Sorry but an error occurred.")
        else:
            try:
                song_queue.add_song(m['nick'], uri)
            except SongQueue.FullUserError:
                onend_text = error("Sorry but your queue is full. Wait until one of your songs finishes and try adding again.")
            except Exception:
                onend_text = error("Sorry but an error occurred.")
        sync_write_fifo(
            f"[[{m['nick']}]] {onend_text}")

    try:
        thread_pool.add_task(on_add)
    except ThreadPool.FullError:
        await bot.send_message(
            error("The bot is currently busy downloading other songs. Try again soon."),
            nick,
        )
        return


@utils.custom_handler("dccreject")
def on_dcc_reject(**m):
    logger.info(f"User Rejected {m=}")


@utils.regex_cmd_with_messsage(r"^(.+)$")
def all_msgs(args: re.Match, msg: Message):
    if msg.nick not in sonic_pi_users or msg.message.strip().startswith(PREFIX):
        return
    sonic_pi_users[msg.nick].append(args[1])

async def onconnect(bot: IrcBot):
    async def message_handler(text):
        match = re.match(r"^\[\[([^\]]+)\]\] (.*)$", text)
        if match:
            channel, text = match.groups()
            logging.debug(
                f" Message relay server handler regex: {channel=}, {text=}")
            await bot.send_message(text, channel)
            return
        for channel in CHANNELS:
            logging.debug(
                f" Message relay server handler simple: {channel=}, {text=}")
            await bot.send_message(text, channel)

    async def mpd_player_handler():
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        song_queue.update()
        await message_handler(f"[{Color(timestamp, fg=Color.random()).str} UTC] - Playing: {mpd_client.current_song_name()}")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(
            listen_loop, MESSAGE_RELAY_FIFO_PATH, message_handler)
        nursery.start_soon(mpd_loop_with_handler, mpd_player_handler)

utils.setHelpHeader(Color("RADIO BOT COMMANDS", fg=Color.cyan).str)
utils.setHelpBottom(
    Color("You can learn more about sonic pi at: https://sonic-pi.net/tutorial.html", bg=Color.black).str)

if __name__ == "__main__":
    utils.setLogging(LOG_LEVEL, LOGFILE)
    bot = IrcBot(HOST, PORT, NICK, CHANNELS, PASSWORD, use_ssl=PORT == 6697,
                 dcc_host=DCC_HOST, dcc_ports=DCC_PORTS, dcc_announce_host=DCC_ANNOUNCE_HOST)
    bot.runWithCallback(onconnect)
