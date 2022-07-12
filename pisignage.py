import httpx
import os
import wget
import hashlib
import subprocess
import time
import psutil
import json

BASE_URL = 'https://pisignage.sagebrush.dev/pisignage_api'


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

def startDisplay(controlFile, signageFile):
# def startDisplay(signageFile):

    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')

    filename = wget.download(signageFile, out='/tmp/signageFile')
    # scriptfile = wget.download('https://pisignage.sagebrush.dev/pisignage_api/media/video.html', out='/tmp/controlFile.html')
    scriptfile = wget.download(controlFile, out='/tmp/controlFile.html')

    print(filename)
    print(scriptfile)

    os.environ['DISPLAY'] = ':0'

    chrome = subprocess.Popen(["chromium-browser", "--kiosk", "--autoplay-policy=no-user-gesture-required", "/tmp/controlFile.html"])

    return chrome

def startWebDisplay(signageFile):
    # def startDisplay(signageFile):

    if os.path.exists('/tmp/webPage.html'):
        os.remove('/tmp/webPage.html')

    filename = wget.download(signageFile, out='/tmp/webPage.html')

    print(filename)

    os.environ['DISPLAY'] = ':0'

    chrome2 = subprocess.Popen(["chromium-browser", "--kiosk", "--autoplay-policy=no-user-gesture-required", "/tmp/webPage.html"])

    return chrome2


def main():

    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
    if os.path.exists('/tmp/webPage.html'):
        os.remove('/tmp/webPage.html')
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')
        
    chromePID = None

    while True:
        if os.path.exists('/tmp/signageFile'):
            hash = md5checksum('/tmp/signageFile')
        else:
            hash = 0
            
        if os.path.exists('/tmp/webPage.html'):
            hash = md5checksum('/tmp/webPage.html')
        else:
            hash = 0

        print(f"Pi Hash: {hash}")
        params = {}
        piName = os.uname()[1]
        params["name"] = piName
        params["hash"] = hash

        try:
            response = httpx.post(f'{BASE_URL}/piConnect', json=params, timeout=None)
            print(response)
            print(response.json())
            status = response.json()['status']
            print(f"Status: {status}")

            if status == "Command":
                print("do command things")
                controlFile = response.json()['scriptPath']
                signageFile = response.json()['contentPath']
                print(signageFile, controlFile)

            elif status =="NoChange":
                print("I am sentient!")

            else:
                if os.path.exists('/tmp/signageFile'):
                    os.remove('/tmp/signageFile')
                if os.path.exists('/tmp/webPage.html'):
                    os.remove('/tmp/webPage.html')
                if os.path.exists('/tmp/controlFile.html'):
                    os.remove('/tmp/controlFile.html')
                if chromePID:
                    kill(chromePID.pid)
                controlFile = response.json()['scriptPath']
                signageFile = response.json()['contentPath']
                if controlFile == '':
                    chromePID = startWebDisplay(signageFile)
                else:
                    chromePID = startDisplay(controlFile, signageFile)
                # chrome = startDisplay(signageFile)

            os.environ['DISPLAY'] = ':0'
            subprocess.run(["scrot", "-o", "-z", f"/tmp/{piName}.png"], check=True)

            data = {'piName': piName}
            files = {'file': open(f'/tmp/{piName}.png', 'rb')}
            r = httpx.post(f'{BASE_URL}/UploadPiScreenshot', data=data, files=files, timeout=None)

            print("sleeping...")
            time.sleep(30)
        except Exception as e:
            print(e)
            print("waiting due to server broken")
            time.sleep(60)

if __name__ == "__main__":
    main()