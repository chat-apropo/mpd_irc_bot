# MPD BOT

A radio bot that integrates mpd and even features a live sonic pi repl. This is the bot I use in radio for the irc at irc.dot.org.es.

Blog post about it: https://blog.mattf.tk/series/coding/3.html 

## Running sonic pi on a vps

- Launch pulseaudio
`pulseaudio --start`

- Launch jack
`jackd -d dummy`

- Launch sonic pi
`sonic-pi-tool start-server`

- Comfort noise
Genereate wav: `sox -c1 -n result.wav synth 10 sin 25000 vol 1`
Play in loop: `mpv -loop result.wav`

- Stream:
  `darkice -c .darkice.conf`

  Config
```
[general]
duration        = 0
bufferSecs      = 5
reconnect       = yes
realtime        = yes
rtprio          = 3

[input]
device          = pulse
#paSourceName    = 0.monitor
sampleRate      = 44100
bitsPerSample   = 16
channel         = 2

[icecast2-0]
bitrateMode     = cbr
format          = vorbis
bitrate         = 128
server          = radio.dot.org.es
port            = 8000
password        = passwordherehahaha
mountPoint      = playground.ogg
name            = Sonic Pi
description     = Sonic Pi REPL
url             = https://radio.dot.org.es
genre           = radio
public          = yes
```


Make sure to redirect the "Pulseaudio to jack" source into the "jack to pulseaudio" sink for jack so that the mpv comfort noise is streamed. This is needed because ogg doesn't stream silence.
