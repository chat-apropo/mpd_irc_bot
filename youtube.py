import yt_dlp as youtube_dl


def chapters(uri):
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

def download_audio(link, keep_video):
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'ffmpeg-location': './',
        'outtmpl': "./%(id)s.%(ext)s",
        'keepvideo': 'True' if keep_video else 'False'
    }
    _id = link.strip()
    meta = youtube_dl.YoutubeDL(ydl_opts).extract_info(_id)
    save_location = meta['id'] + ".mp3"
    print(save_location)
    return save_location

if __name__ == "__main__":
    from sys import argv
    download_audio(argv[1], False)
