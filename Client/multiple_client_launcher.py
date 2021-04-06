import os
import signal
import sys

if len(sys.argv) > 1 and sys.argv[1].isdigit():
    N_CLIENTS = int(sys.argv[1])
else:
    N_CLIENTS = 10

print("nb clients :", N_CLIENTS)

os.makedirs("logs", exist_ok=True)
pids = [0] * N_CLIENTS
command = "./venv/bin/python3 client.py".split()


def kill_handler(sig, frame=None):
    print("Receive signal", sig, signal.Signals(sig).name)
    for pid in pids:
        if pid:
            try:
                print("kill", pid)
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


signal.signal(signal.SIGTERM, kill_handler)
signal.signal(signal.SIGINT, kill_handler)

for i in range(N_CLIENTS):
    pid = os.fork()
    if pid <= 0:
        print("Start fils", i)
        with open(f"./logs/logs_{i}.log", "w") as file:
            os.dup2(file.fileno(), sys.stdout.fileno())
            os.dup2(file.fileno(), sys.stderr.fileno())
            os.execv(command[0], command)
        exit(0)
    else:
        pids[i] = pid

for pid in pids:
    print("Waiting", pid)
    os.waitpid(pid, 0)
print("End")
