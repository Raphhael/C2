# Simple C2 Client / Server

## Features

Multi-threaded server can :
- Upload files on client pool
- Download files from clients
- Take screenshots
- Execute shell commands

## Test

- Install requirements :
  - `pip3 install -r Clients/requirements.txt`
  - `pip3 install -r Server/requirements.txt`
- Start server : 
  - `cd Server && python server.py`
- In another shell, start for example 20 clients
  - `cd Client && python multiple_client_launcher.py 20`
- Execute commands in server prompt :
  - `upload "example.txt" "client.txt"`
  - `download client.txt`
  - `screenshot`
  - `sh echo $$`
  - `sh whoami`
