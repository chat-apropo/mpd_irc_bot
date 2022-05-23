# Mostly copied from: https://github.com/emlyn/sonic-pi-tool/, under MPL2 license

import html
import logging
import os
import re
import socket
import sys
import time

from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer

SERVER_OUTPUT = "~/.sonic-pi/log/server-output.log"


logger = logging.getLogger()


class Server:
    """Represents a running instance of Sonic Pi."""

    preamble = '@osc_server||=SonicPi::OSC::UDPServer.new' + \
               '({},use_decoder_cache:true) #__nosave__\n'

    def __init__(self, host, cmd_port, osc_port, send_preamble, verbose):
        self.client_name = 'SONIC_PI_TOOL_PY'
        self.host = host
        self._cmd_port = cmd_port
        self._cached_cmd_port = None
        self.osc_port = osc_port
        # fix for https://github.com/repl-electric/sonic-pi.el/issues/19#issuecomment-345222832
        self.send_preamble = send_preamble
        self._cmd_client = None
        self._osc_client = None

    def get_cmd_port(self):
        return self._cmd_port

    def cmd_client(self):
        if self._cmd_client is None:
            self._cmd_client = OSCClient(self.host, self.get_cmd_port(),
                                         encoding='utf8')
        return self._cmd_client

    def osc_client(self):
        if self._osc_client is None:
            self._osc_client = OSCClient(self.host, self.osc_port,
                                         encoding='utf8')
        return self._osc_client

    def get_preamble(self):
        if self.send_preamble:
            return Server.preamble.format(self.get_cmd_port())
        return ''

    def send_cmd(self, msg, *args):
        client = self.cmd_client()
        logger.info("Sending command to {}:{}: {} {}"
                    .format(self.host, self.get_cmd_port(), msg,
                            ', '.join(repr(v) for v in (self.client_name,) + args)))
        client.send_message(msg, (self.client_name,) + args)

    def send_osc(self, path, args):
        def parse_val(s):
            try:
                return int(s)
            except ValueError:
                pass
            try:
                return float(s)
            except ValueError:
                pass
            if len(s) > 1 and s[0] == '"' and s[-1] == '"':
                return s[1:-1]
            return s

        client = self.osc_client()
        parsed = [parse_val(s) for s in args]
        logger.info("Sending OSC message to {}:{}: {} {}"
                    .format(self.host, self.osc_port, path,
                            ', '.join(repr(v) for v in parsed)))
        client.send_message(path, parsed)

    def check_if_running(self):
        cmd_listening = Server.port_in_use(self.get_cmd_port())
        logger.info("The command port ({}) is {}in use".format(self.get_cmd_port(),
                                                               "" if cmd_listening else "not "))
        osc_listening = Server.port_in_use(self.osc_port)
        logger.info("The OSC port ({}) is {}in use".format(self.osc_port,
                                                           "" if osc_listening else "not "))
        osc_listening = True
        if cmd_listening and osc_listening:
            logger.info("Sonic Pi is running, and listening on port {} for commands and {} for OSC"
                        .format(self.get_cmd_port(), self.osc_port), True)
            return 0
        elif not cmd_listening and not osc_listening:
            logger.info("Sonic Pi is not running", True)
            return 1
        else:
            logger.info("Sonic Pi is not running properly, or there's an issue with the port numbers",
                        True)
            return 2

    def stop_all_jobs(self):
        self.send_cmd('/stop-all-jobs')

    def run_code(self, code):
        self.send_cmd('/run-code', self.get_preamble() + code)

    def start_recording(self):
        self.send_cmd('/start-recording')

    def stop_and_save_recording(self, path):
        self.send_cmd('/stop-recording')
        self.send_cmd('/save-recording', path)

    @staticmethod
    def port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                return True
        return False

    @staticmethod
    def determine_command_port():
        try:
            with open(os.path.expanduser(SERVER_OUTPUT)) as f:
                for line in f:
                    m = re.search('^Listen port: *([0-9]+)', line)
                    if m:
                        return int(m.groups()[0])
        except FileNotFoundError:
            pass

    @staticmethod
    def handle_log_info(style, msg):
        msg = "=> {}".format(msg)
        logger.info(msg)
        logger.info()

    @staticmethod
    def handle_multi_message(run, thread, time, n, *msgs):
        msg = "{{run: {}, time: {}}}".format(run, time)
        logger.info(msg)
        for i in range(n):
            typ, msg = msgs[2 * i: 2 * i + 2]
            for j, line in enumerate(msg.splitlines()):
                if i < n - 1:
                    prefix = "  ├─ " if j == 0 else "  │"
                else:
                    prefix = "  └─ " if j == 0 else "   "
                logger.info(f"{prefix}, {line}, {typ}")
        logger.info()

    @staticmethod
    def handle_runtime_error(run, msg, trace, line_num):
        lines = html.unescape(msg).splitlines()
        prefix = "Runtime Error: "
        for line in lines:
            logger.debug(f"{prefix=} {line=}")
            prefix = ""
        logger.debug(html.unescape(trace))

    @staticmethod
    def handle_syntax_error(run, msg, code, line_num, line_s):
        logger.error("Error: " + html.unescape(msg))
        prefix = "[Line {}]: ".format(line_num) if line_num >= 0 else ""
        logger.error(f"{prefix=}, {code=}")

    def follow_logs(self):
        try:
            server = OSCThreadServer(encoding='utf8')
            server.listen(address='127.0.0.1', port=4558, default=True)
            server.bind('/log/multi_message', self.handle_multi_message)
            server.bind('/multi_message', self.handle_multi_message)
            server.bind('/log/info', self.handle_log_info)
            server.bind('/info', self.handle_log_info)
            server.bind('/error', self.handle_runtime_error)
            server.bind('/syntax_error', self.handle_syntax_error)
            while True:
                time.sleep(1)
        except Exception as e:
            return e


def eval_stdin(server: Server):
    server.run_code(sys.stdin.read())


def eval_file(server: Server, path):
    server.run_code(path.read())

def osc(server: Server, path, args):
    server.send_osc(path, args)

notes_map = {
        'z': ':c1',
        's': ':cs1',
        'x': ':d1',
        'd': ':ds1',
        'c': ':e1',
        'v': ':f1',
        'g': ':fs1',
        'b': ':g1',
        'h': ':gs1',
        'n': ':a1',
        'j': ':as1',
        'm': ':b1',
        ',': ':c2',
        'l': ':cs2',
        '.': ':d2',
        'q': ':c2',
        '2': ':cs2',
        'w': ':d2',
        '3': ':ds2',
        'e': ':e2',
        'r': ':f2',
        '5': ':fs2',
        't': ':g2',
        '6': ':gs2',
        'y': ':a2',
        '7': ':as2',
        'u': ':b2',
        'i': ':c3',
        '9': ':cs3',
        'o': ':d3',
        '0': ':ds3',
        'p': ':e3',
        '-': ':fs3',
}


class NoteNotFound(Exception):
    pass

def convert_to_notes(kb_notes: str, octave: int):
    notes = []
    for note in kb_notes:
        if note in notes_map:
            oct = int(notes_map[note][-1]) + octave - 1
            name = notes_map[note][:-1]
            notes.append(f"{name}{oct}")
        else:
            raise NoteNotFound(note)
    return notes


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    # server = Server(host, cmd_port, osc_port, preamble, verbose)
    server = Server("10.176.67.210", 4557, 4660, None, True)
    code = ' '.join(sys.argv[1:])
    server.run_code(code)
    print("READING STDIN:")
    server.run_code(sys.stdin.read())
    input("Press enter to stop")
    server.stop_all_jobs()
