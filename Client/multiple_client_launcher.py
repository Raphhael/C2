"""
Start multiple fake clients for testing purpose
"""

import os
import sys
from signal import signal, Signals, SIGTERM, SIGINT

if len(sys.argv) > 1 and sys.argv[1].isdigit():
    N_CLIENTS = int(sys.argv[1])
else:
    N_CLIENTS = 10

print("nb clients :", N_CLIENTS)

os.makedirs("logs", exist_ok=True)
PIDS = [0] * N_CLIENTS
COMMAND = "./venv/bin/python3 client.py -t 127.0.0.1:9999".split()


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

for i in range(N_CLIENTS):
    pid = os.fork()
    if pid <= 0:
        print("Start fils", i)
        with open(f"./logs/logs_{i}.log", "w") as file:
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
