"""
This module provide utility functions for C2 Client and C2 Server.

"""
import inspect
from io import SEEK_END, BufferedIOBase, BytesIO
from logging import DEBUG, getLogger, LoggerAdapter
from socket import socket

# IP / PORT ADDED
LOGGER = getLogger('socket')
LOGGER.setLevel(DEBUG)


class C2SocketError(Exception):
    """ Base class for C2Socket Errors """


class RemoteDisconnected(C2SocketError):
    """ Other side is disconnected """


class ReadError(C2SocketError):
    """ An error occurs during socket read operation """


class SendError(C2SocketError):
    """ An error occurs during socket write operation """


class C2Socket:
    """ Class providing useful methods for communication between server and client.

    Attributes:
        RECV_BUFFER_SIZE (bytes): TCP buffer size for read op
        SEND_BUFFER_SIZE (bytes): TCP buffer size for write op

    Notes:
        The client / server communication is done with simple packet structed like :
        0                   1                   2                   3
        0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                          Data length                          |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                                                               |
        +                         Variable Data                         +
        |                                                               |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    _RECV_BUFFER_SIZE = 128_000
    _SEND_BUFFER_SIZE = 64_000

    def __init__(self, ip, port, sock: socket = None):
        """ Create a socket and connect to destination ip:port.

        If sock parameter is given, it must be a valid connected socket.

        Args:
            ip (str): Destination IP
            port (int): Destination port
            sock (socket): Valid connected socket
        """
        self.ip_address = ip
        self.port = port
        self.logger = LoggerAdapter(LOGGER, {'ip': ip, 'port': port})
        if not sock:
            self.sock = socket()
            self.sock.connect((ip, port))
            self.logger.debug("Connected")
        else:
            self.sock = sock

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.logger.debug("__exit__ called")
        self.sock.close()

    def __repr__(self):
        return f"Socket<{self.ip_address}:{self.port}>"

    def _read(self, length, writer_io=None):
        """ Read n bytes on socket

        Args:
            length (int): length of bytes to read
            writer_io (BufferedIOBase): Buffer to write data read on socket. If None, all data is stored in a variable

        Returns (bytes): Data read if `writer_io` is None, else total number of bytes read

        Raises:
            RemoteDisconnected: Blocking read 0 bytes => remote disconnected
            ReadError: Read unattended amount of data

        """
        self.logger.debug("read(%s, %s)", length, writer_io)
        buffer_writer = writer_io or BytesIO()
        i = 0

        while i < length:
            buffer_len = min(C2Socket._RECV_BUFFER_SIZE, length - i)
            try:
                buffer = self.sock.recv(buffer_len)
            except OSError as err:
                raise RemoteDisconnected(f"Got error {type(err)} : {err}")

            if len(buffer) == 0:
                raise RemoteDisconnected("Read 0 bytes. Disconnected")
            if len(buffer) > buffer_len:
                raise ReadError(f"Read {len(buffer)} bytes, not {buffer_len} bytes. Disconnected")

            buffer_writer.write(buffer)
            i += len(buffer)

        self.logger.debug("read(%s), read=%s", length, i)

        if writer_io:
            return i
        buffer_writer.seek(0)
        return buffer_writer.read()

    def _send_int(self, integer):
        """ Send an integer

        Args:
            integer (int): the int
        """
        encoded = integer.to_bytes(4, 'big')
        self.sock.send(encoded)
        self.logger.debug("Send integer %s (%s)", integer, encoded)

    def _read_int(self):
        """ Read an integer

        Returns (int): The next integer

        """
        data = self._read(4)
        return int.from_bytes(data, 'big')

    def read_into_file(self, file):
        """ Convenience function to receive remote file in buffered io object

        Args:
            file (BufferedIOBase): Local file we want to write

        """
        file_len = self._read_int()
        self._read(file_len, file)

    def read_packet(self):
        """ Read packet and returns data

        Returns (bytes): The data
        """
        self.logger.debug("read_packet")
        pkt_len = self._read_int()
        self.logger.debug("read_packet of len %s", pkt_len)
        pkt_data = self._read(pkt_len)
        self.logger.debug("read_packet : %s", pkt_data[:100])
        return pkt_data

    def send_file(self, file):
        """ Send file

        Args:
            file (BufferedIOBase): File in binary read

        Returns (bool): True if no errors

        Notes:
            File needs to be seekable
            File is sent from beginning (offset 0)
        """
        try:
            length = file.seek(0, SEEK_END)
            self._send_int(length)
            file.seek(0)
            return length == self.sock.sendfile(file)
        except OSError as err:
            raise SendError(f"{self} : send_file raise exception {type(err)} : {err}")

    def send_packet(self, data):
        """ Send packet

        Args:
            data (bytes): Data to send

        Returns (bool): True if success

        """
        self.logger.debug("send_packet, data of len %s", len(data))
        payload = len(data).to_bytes(4, 'big') + data
        try:
            if self.sock.sendall(payload) is not None:
                raise SendError()
            self.logger.debug("send_packet, total len %s", len(payload))
            return True
        except OSError as err:
            raise SendError(f"Error sending payload of length {len(data)} : {type(err)} : {err}")


class Commands:
    """ Base class for executing commands

    Notes :
        To add a command, just add a method ending by `_command` (for example : test_command),
        with the attempted parameters.

        To execute a command, create an instance of this object, then execute method `is_valid` then `execute` method.

    """

    def __init__(self, sock: C2Socket, cmd, params, raw_input):
        """

        Args:
            sock (socket): Remote host
            cmd (str): Command name
            params (list[str]): List of parameters
            raw_input (str): user input
        """
        self.sock = sock
        self.cmd = cmd
        self.params = params
        self.function = self.get_function()
        _, *content = raw_input.split(maxsplit=1)
        self.input = content[0] if content else ''

    def is_valid(self):
        """ Check if the command exists and has good parameters

        Returns (bool): True if no errors, False otherwise.

        """
        if not self.function:
            return False

        fun_params = dict(inspect.signature(self.function).parameters)
        fun_params.pop('self', None)
        fun_params.pop('cls', None)
        positional = len([1 for p in fun_params.values() if p.kind == p.VAR_POSITIONAL])

        if len(self.params) > len(fun_params) and not positional:
            self.sock.logger.debug("Too much parameters for function %s : %s", self.function.__name__, self.params)
        else:
            required_params = [fp for fp in fun_params.values() if fp.default == inspect._empty]
            missing = required_params[len(self.params):]
            if missing:
                self.sock.logger.error("Missing parameters for function %s{self.function.__name__} :")
                self.sock.logger.error("- Given parameters : %s", self.params)
                self.sock.logger.error("- Missing parameters : %s", ', '.join(map(lambda p: p.name, missing)))
            else:
                return True
        return False

    def get_function(self):
        """ Get the function associated with command

        Returns: Function or None if not found

        """
        fct_name = f"command_{self.cmd}"
        fct = getattr(self, fct_name, None)
        if fct is not None:
            return fct
        self.sock.logger.warning("Missing method %s of class Commands.", fct_name)

    def execute(self):
        """ Execute the function """
        if not self.function:
            return
        self.sock.logger.debug("""Starting %s("%s")""", self.function.__name__, '","'.join(self.params))
        try:
            self.function(*self.params)
        except (SendError, ReadError) as err:
            self.sock.logger.error("Commands.%s failed because : %s %s", self.function.__name__, type(err), err)
