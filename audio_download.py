import logging
import filecmp
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp as youtube_dl
from slugify import slugify

AUDIO_EXTENSIONS = {"wav", "mp3", "ogg", "flac", "aiff", "wma", "m4a"}
MAX_AUDIO_LENGTH = 60 * 30
MAX_FILE_SIZE = 1024**2 * 40
YT_VALID_VIDEO_DOMAINS = ["youtube.com", "youtu.be"]

logger = logging.getLogger()

class MaxFilesize(Exception):
    pass

class MaxAudioLength(Exception):
    pass

class FailedToProcess(Exception):
    pass

class FailedToDownload(Exception):
    pass

class ExtensionNotAllowed(Exception):
    pass

def allowed_file(filename):
    return '.' in filename and \
           filename.split('.')[-1].lower() in AUDIO_EXTENSIONS

def get_audio_length(audio_path):
    audio_path = shlex.quote(audio_path)
    return float(subprocess.check_output(f"ffprobe -i {audio_path} -show_entries format=duration -v quiet -of csv=\"p=0\"", shell=True).decode().strip())

def yt_chapters(uri):
    ydl_opts = {"forcejson": True, "simulate": True}
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(uri, download=False)
        duration = result["duration"]
        if "chapters" in result:
            chapter_length = len(result["chapters"])
            on_chapter = True
            chapter_index = 0
            chapters = result["chapters"]
            title = f'{result["title"]}: {result["chapters"][0]["title"]}'
        else:
            on_chapter = False
            title = result["title"]

def move_file(from_path: str, raw_filename: str, out_dir: str, suffix: str):
    return_path = os.path.expanduser(os.path.join(out_dir, slugify(raw_filename) + suffix))
    if Path(return_path).is_dir():
        logger.info("User attempted to overwrite directory: {}".format(return_path))
        raise FailedToProcess
    if Path(return_path).is_file():
        if filecmp.cmp(from_path, return_path):
            os.remove(from_path)
            return return_path
        return move_file(from_path, raw_filename, out_dir, "_" + suffix)
    os.rename(from_path, return_path)
    logger.info(f"Downloaded file to {return_path=}")
    return return_path

def yt_download_audio(link: str, out_dir: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg-location': './',
            'outtmpl': f"{tmpdir}/%(id)s.%(ext)s",
            'keepvideo': 'False'
        }
        _id = link.strip()
        try:
            meta = youtube_dl.YoutubeDL({**ydl_opts, "simulate": True}).extract_info(_id)
        except Exception:
            raise FailedToDownload
        if meta.get("duration", MAX_AUDIO_LENGTH) > MAX_AUDIO_LENGTH:
            raise MaxAudioLength
        try:
            meta = youtube_dl.YoutubeDL(ydl_opts).extract_info(_id)
        except Exception:
            raise FailedToDownload
        save_location = meta['id'] + ".mp3"
        return move_file(tmpdir + "/" + save_location, meta['title'], out_dir, ".mp3")

def download_audio(url: str, out_dir: str):
    if ".".join(urlparse(url).netloc.split(".")[-2:]) in YT_VALID_VIDEO_DOMAINS:
        return_path = yt_download_audio(url, out_dir)
    else:
        filename = url.split("/")[-1]
        if not allowed_file(filename):
            raise ExtensionNotAllowed
        suffix = "." + filename.split(".")[-1]
        audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            if subprocess.call(["curl", url, "--max-filesize", str(MAX_FILE_SIZE), "--output", audio_path.name]):
                raise MaxFilesize
        except Exception:
            raise FailedToDownload
        print("Downloaded file: {}".format(audio_path.name))

        try:
            if get_audio_length(audio_path.name) > MAX_AUDIO_LENGTH:
                os.remove(audio_path.name)
                raise MaxAudioLength
        except Exception:
            os.remove(audio_path.name)
            raise FailedToProcess
        return_path = move_file(audio_path.name, filename[:-len(suffix)], out_dir, suffix)
    return return_path

if __name__ == "__main__":
    from sys import argv
    print(download_audio(argv[1], "./test"))
