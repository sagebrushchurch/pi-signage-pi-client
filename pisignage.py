from cmath import log
from traceback import print_exc
import os
import hashlib
import subprocess
import time
import psutil
import httpx
import wget
import json
import cec


BASE_URL = 'https://pisignage.sagebrush.dev/pisignage_api'
logList = []

def clearFiles():
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
    if os.path.exists('/tmp/webPage.html'):
        os.remove('/tmp/webPage.html')
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')
        
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

    clearFiles()

    wget.download(signageFile, out='/tmp/signageFile')
    wget.download(controlFile, out='/tmp/controlFile.html')

    os.environ['DISPLAY'] = ':0'

    chrome = subprocess.Popen(["chromium-browser", "--kiosk",
                               "--autoplay-policy=no-user-gesture-required",
                               "/tmp/controlFile.html", ],
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return chrome

def startWebDisplay(signageFile):

    clearFiles()

    wget.download(signageFile, out='/tmp/webPage.html')

    os.environ['DISPLAY'] = ':0'

    chrome2 = subprocess.Popen(["chromium-browser", "--kiosk",
                                "--autoplay-policy=no-user-gesture-required",
                                "/tmp/webPage.html"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return chrome2

def recentLogs(logMessage: str):

    logList.append(logMessage)
    
    print(logMessage)
    return logList


def main():

    cec.init()
    tv = cec.Device(cec.CECDEVICE_TV)
    clearFiles()
    chromePID = None
    tvStatusFlag = False
    tvStatus = "False"

    while True:
        recentLogs(tvStatus)
        if os.path.exists('/tmp/signageFile'):
            hash = md5checksum('/tmp/signageFile')
        elif os.path.exists('/tmp/webPage.html'):
            hash = md5checksum('/tmp/webPage.html')
        else:
            hash = 0

        params = {}
        piName = os.uname()[1]
        params["name"] = piName
        params["hash"] = hash
        params["tvStatus"] = tvStatus
        params["piLogs"] = logList

        try:
            response = httpx.post(f'{BASE_URL}/piConnect', json=params, timeout=None)
            status = response.json()['status']
            recentLogs(f"Status: {status}")

            if status == "Command":
                recentLogs("do command things")
                commandFile = response.json()['scriptPath']
                commandFlags = response.json()['contentPath']
                wget.download(commandFile, out='/tmp/commandfile.py')
                try:
                    subprocess.Popen(["/usr/bin/python3", "/tmp/commandfile.py", f"--{commandFlags}"])
                except subprocess.CalledProcessError as e:
                    recentLogs(e)
                    recentLogs("probably unsupported TV")
                    
                recentLogs(commandFlags)
                recentLogs(commandFile)

            elif status =="NoChange":
                recentLogs("I am sentient!")
                try:
                    tvStatus = str(tv.is_on())
                except OSError:
                    tvStatus = "UnsupportedTV"

            else:
                if status == "DEFAULT":
                    if tvStatusFlag:
                        recentLogs("turning tv off")
                        tv.standby()
                        tvStatusFlag = False
                        try:
                            tvStatus = str(tv.is_on())
                        except OSError:
                            tvStatus = "UnsupportedTV"
                else:
                    if not tvStatusFlag:
                        recentLogs("turning tv on")
                        tv.power_on()
                        tvStatusFlag = True
                        try:
                            tvStatus = str(tv.is_on())
                        except OSError:
                            tvStatus = "UnsupportedTV"
                clearFiles()
                if chromePID:
                    kill(chromePID.pid)
                controlFile = response.json()['scriptPath']
                signageFile = response.json()['contentPath']
                if controlFile == '':
                    chromePID = startWebDisplay(signageFile)
                else:
                    chromePID = startDisplay(controlFile, signageFile)

            os.environ['DISPLAY'] = ':0'
            subprocess.run(["scrot", "-q", "5", "-t", "10", "-o", "-z", f"/tmp/{piName}.png"], 
                           check=True)

            data = {'piName': piName}
            files = {'file': open(f'/tmp/{piName}-thumb.png', 'rb')}
            r = httpx.post(f'{BASE_URL}/UploadPiScreenshot', data=data, files=files, timeout=None)

            recentLogs("I sleep...")
            time.sleep(30)
        except psutil.NoSuchProcess:
        # Sometimes chrome's pid changes, i think its cuz of the redirect for webpage viewing
            time.sleep(1)
            recentLogs("chrome pid lost, restarting")
        except Exception as e:
        # Keeping general exception so that loop never crashes out
            recentLogs('type is: ' + e.__class__.__name__)
            print_exc()
            recentLogs("Caught a error...waiting and will try again")
            time.sleep(15)

if __name__ == "__main__":
    main()