"""
Start multiple fake clients for testing purpose
"""

import os
import sys
from argparse import ArgumentParser
from signal import signal, Signals, SIGTERM, SIGINT

parser = ArgumentParser()
parser.add_argument('-n', '--nb-clients', default=10, type=int, help='Number of clients created')
parser.add_argument('-t', '--target', default='127.0.0.1', help="Server IP")
parser.add_argument('-p', '--port', default=9999, type=int, help="Server port")
parser.add_argument('-x', '--executable', default='./venv/bin/python3', help="Python executable")
parser.add_argument('-l', '--logs', default='./logs', help="Logs path")
args = parser.parse_args()

COMMAND = f"{args.executable} client.py -t {args.target}:{args.port}".split()

print("nb de clients :", args.nb_clients)
print("commande :", COMMAND)
print("logs :", args.logs)

os.makedirs(args.logs, exist_ok=True)

PIDS = [0] * args.nb_clients


def kill_handler(sig, frame=None):
    """ On kill, kill also all clients

    Args:
        sig (int): Signal
        frame: required
    """
    print("Receive signal", sig, Signals(sig).name)
    for child_pid in PIDS:
        if child_pid:
            try:
                print("kill", child_pid)
                os.kill(child_pid, SIGTERM)
            except ProcessLookupError:
                pass


signal(SIGTERM, kill_handler)
signal(SIGINT, kill_handler)

for i in range(args.nb_clients):
    pid = os.fork()
    if pid <= 0:
        print("Start fils", i)
        with open(f"{args.logs}/logs_{i}.log", "a+") as file:
            os.dup2(file.fileno(), sys.stdout.fileno())
            os.dup2(file.fileno(), sys.stderr.fileno())
            os.execv(COMMAND[0], COMMAND)
        sys.exit(0)
    else:
        PIDS[i] = pid

for pid in PIDS:
    print("Waiting", pid)
    os.waitpid(pid, 0)
print("End")
