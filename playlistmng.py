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


import threading
from copy import deepcopy
from dataclasses import dataclass
from logging import getLogger

from mpd.base import CommandError

from mpd_client import MPDClient

logger = getLogger()


class ThreadPool:
    """A very dumb thread pool implementation.

    The only goal here is to limit the number of simulaneous thread that
    can be run and encapsulate the threading module.
    """

    class FullError(Exception):
        pass

    def __init__(self, max_threads):
        self.max_threads = max_threads
        self.threads = []
        self.lock = threading.Lock()

    def add_task(self, func, *args, **kwargs):
        """Add a task to the thread pool."""
        with self.lock:
            if len(self.threads) >= self.max_threads:
                raise ThreadPool.FullError()
            thread = threading.Thread(
                target=func, args=args, kwargs=kwargs, daemon=True)
            thread.start()
            self.threads.append(thread)

    def wait_completion(self):
        """Wait for all threads to complete."""
        with self.lock:
            for thread in self.threads:
                thread.join()
            self.threads = []


@dataclass
class Song:
    id: str
    uri: str
    from_nick: str


class SongQueue:
    """Global song queue for all users.

    This class is responsible for adding songs, limiting each user's
    queue and automatically removing them after they are played.
    """

    class FullUserError(Exception):
        pass

    class PositionNotFoundError(Exception):
        pass

    def __init__(self, max_len: int, mpd_client: MPDClient):
        self.queues = {}
        self.max_len = max_len
        self.mpd_client = mpd_client
        self.last_pos = None

    def __len__(self) -> int:
        return sum(len(self.queues[user]) for user in self.queues)

    def next_pos(self) -> int:
        """Return the position of the next song to be added."""
        pos = self.mpd_client.pos()
        if self.last_pos is None:
            return pos + 1
        max_pos = self.mpd_client.length()
        return min(self.last_pos + 1, max_pos)

    def add_song(self, user: str, uri: str) -> Song:
        """Add a song to the queue.

        Returns its position. Can raise FullUserError.
        """
        if user not in self.queues:
            self.queues[user] = []
        if len(self.queues[user]) >= self.max_len:
            raise SongQueue.FullUserError()
        pos = self.next_pos()
        try:
            self.mpd_client.add_at_pos(uri, pos)
        except AttributeError:
            logger.error("Failed to add song to queue")
            raise AttributeError("Failed to add song to queue")
        song_id = self.mpd_client.get_id_at_pos(pos)
        song = Song(song_id, uri, user)
        self.queues[user].append(song)
        logger.info(
            f"Added song {uri=} to queue of {user=} at {pos=} with {song_id=}")
        self.last_pos = pos
        return song

    def can_add(self, user: str) -> bool:
        """Return whether a user can add a song to the queue."""
        try:
            return len(self.queues[user]) < self.max_len
        except KeyError:
            return True

    def user_songs(self, user: str) -> [Song]:
        """Return the songs of a user."""
        return self.queues[user]

    def all_songs(self) -> [Song]:
        """Return all songs in the queue."""
        songs = []
        for user in self.queues:
            songs.extend(self.queues[user])
        return songs

    def keep_all(self, user: str):
        """Keep all songs of a user, removing them from the queue if in any,
        making sure they won't be automatically removed.

        Can raise KeyError.
        """
        for song in deepcopy(self.queues[user]):
            self.queues[user].remove(song)
            logger.info(
                f"Keeping song {song.id=} from queue of {song.from_nick=}")

    def keep_song(self, pos: int):
        """Stops tracking a song, removing it from the queue if in any, making
        sure it wont get automatically removed.

        Can raise PositionNotFoundError and KeyError.
        """
        try:
            song_id = self.mpd_client.get_id_at_pos(pos)
        except CommandError:
            raise SongQueue.PositionNotFoundError()
        for user in self.queues:
            for song in deepcopy(self.queues[user]):
                if song.id == song_id:
                    self.queues[user].remove(song)
                    logger.info(
                        f"Keeping song {song_id=} from queue of {user=} at pos {pos=}")
                    return True
        raise SongQueue.PositionNotFoundError()

    def update(self):
        """Update the queue by removing songs that are no longer in the user's
        queue.

        A song will be removed when its id is the previous one.
        """
        logger.debug("Updating queue")
        prev_id, id, next_id = self.mpd_client.surrounding_ids()
        logger.debug(f"{prev_id=}, {id=}, {next_id=}")
        pos = self.mpd_client.pos()
        for user in self.queues:
            for song in deepcopy(self.queues[user]):
                # Clear all on playlist reset or when the song is the previous
                logger.debug(f"Checking {song.id=}")
                if pos == 0 or song.id == prev_id:
                    self.queues[user].remove(song)
                    self.mpd_client.remove_id(song.id)
                    logger.info(
                        f"Removed song {song.id=} from queue of {user=}")


async def test():
    # TODO write proper tests someday (a mpd mock server? damn)
    import logging

    from mpd_client import mpd_loop_with_handler
    logging.basicConfig(level=logging.DEBUG)
    songs = ["_mpdbot/wwwyoutubecomwatchvfsbpwd-bac0.m4a",
             "_mpdbot/epica-rivers-official-visualizer.mp3"]
    client = MPDClient("localhost", 6600)
    queue = SongQueue(3, client)
    queue.add_song("test", songs[0])
    queue.add_song("test", songs[0])
    queue.add_song("test", songs[1])
    try:
        queue.add_song("test", songs[1])
        raise ValueError()
    except SongQueue.FullUserError:
        pass
    queue.add_song("otherguy", songs[0])
    pos = queue.next_pos()
    queue.add_song("otherguy", songs[1])
    queue.add_song("thirdguy", songs[0])
    queue.keep_song(pos)
    queue.add_song("thirdguy", songs[1])
    queue.add_song("thirdguy", songs[1])
    try:
        queue.add_song("thirdguy", songs[1])
        raise ValueError()
    except SongQueue.FullUserError:
        pass
    try:
        queue.keep_song(12031)
        raise ValueError()
    except SongQueue.PositionNotFoundError:
        pass
    print(queue.user_songs("test"))
    print(queue.all_songs())
    await mpd_loop_with_handler(queue.update)


if __name__ == "__main__":
    import trio
    trio.run(test)
