import httpx
import json
import os
import asyncio
import wget
import hashlib
import subprocess
import time
import signal
import psutil


def md5checksum(fname):

    md5 = hashlib.md5()

    # handle content in binary form
    f = open(fname, "rb")

    while chunk := f.read(4096):
        md5.update(chunk)

    return md5.hexdigest()

def kill(proc_pid):
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()
    
# def startDisplay(status, controlFile):
def startDisplay(signageFile):
        
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')
        
    filename = wget.download(signageFile, out='/tmp/signageFile')
    scriptfile = wget.download('https://pisignage.sagebrush.dev/pisignage_api/media/video.html', out='/tmp/controlFile.html')
    # scriptfile = wget.download(controlFile, out='/tmp/controlFile.html')
    
    print(filename)
    print(scriptfile)
    
    os.environ['DISPLAY'] = ':0'
    
    chrome = subprocess.Popen(["chromium-browser", "--kiosk", "/tmp/controlFile.html"])
    
    return chrome


async def main():
    
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
        
    while(True):
        async with httpx.AsyncClient() as client:
            try:
                hash = md5checksum('/tmp/signageFile')
            except:
                hash = 0
                
            print(f"Pi Hash: {hash}")
            params = {}
            params["name"] = os.uname()[1]
            params["hash"] = hash

            response = await client.post('https://pisignage.sagebrush.dev/pisignage_api/piConnect', json=params)
            print(response)
            print(response.json())
            status = response.json()['status']
            print(f"Status: {status}")
            
            if not status == "NoChange":
                try:
                    kill(chrome.pid)
                except:
                    print("chrome was not running?")
                #controlFile = response.json()['controlFile']
                signageFile = response.json()['contentPath']
                # chrome = startDisplay(status, controlFile)
                chrome = startDisplay(signageFile)
            input("Press any key")


asyncio.run(main())