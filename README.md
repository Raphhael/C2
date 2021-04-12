# Simple C2 Client / Server

![banner](https://github.com/Raphhael/C2/blob/main/img/banner.min.png?raw=true)

## Features

Multi-threaded server can :

- Upload files on client pool
- Download files from clients
- Take screenshots
- Execute shell commands

## Usage

### Commands
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

### Examples

#### 1. Install server from scratch

![Install server gif](https://github.com/Raphhael/C2/blob/main/img/1%20-%20Server%20install.gif?raw=true)


#### 2. Add some clients

![Add clients gif](https://github.com/Raphhael/C2/blob/main/img/2%20-%20Add%20clients.gif?raw=true)


#### 3. Send slow commands to multiple targets

![Send slow commands gif](https://github.com/Raphhael/C2/blob/main/img/3%20-%20Command%20to%20lot%20of%20targets.gif?raw=true)



#### 4. Take screenshots of clients

![Screenshot gif](https://github.com/Raphhael/C2/blob/main/img/4%20-%20Screenshot.gif?raw=true)



#### 5. Upload and download files

![Upload and download files gif](https://github.com/Raphhael/C2/blob/main/img/5%20-%20Upload%20Download.gif?raw=true)



#### 6. Few additional tests

![SSH and shutdown gif](https://github.com/Raphhael/C2/blob/main/img/6%20-%20Service%20and%20shutdown.gif?raw=true)

---


<small>All the assets used in README.md are stored </small>[here](https://github.com/Raphhael/C2/tree/main/img)

