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

    filename = wget.download(signageFile, out='/tmp/signageFile')
    scriptfile = wget.download(controlFile, out='/tmp/controlFile.html')

    os.environ['DISPLAY'] = ':0'

    chrome = subprocess.Popen(["chromium-browser", "--kiosk",
                               "--autoplay-policy=no-user-gesture-required",
                               "/tmp/controlFile.html", ],
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return chrome

def startWebDisplay(signageFile):

    clearFiles()

    filename = wget.download(signageFile, out='/tmp/webPage.html')

    os.environ['DISPLAY'] = ':0'

    chrome2 = subprocess.Popen(["chromium-browser", "--kiosk",
                                "--autoplay-policy=no-user-gesture-required",
                                "/tmp/webPage.html"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return chrome2


def main():

    cec.init()
    tv = cec.Device(cec.CECDEVICE_TV)
    clearFiles()
    chromePID = None
    tvStatusFlag = False
    tvStatus = "False"

    while True:
        print(tvStatus)
        if os.path.exists('/tmp/signageFile'):
            hash = md5checksum('/tmp/signageFile')
        elif os.path.exists('/tmp/webPage.html'):
            hash = md5checksum('/tmp/webPage.html')
        else:
            hash = 0

        print(f"Pi Hash: {hash}")
        params = {}
        piName = os.uname()[1]
        params["name"] = piName
        params["hash"] = hash
        params["tvStatus"] = tvStatus

        try:
            response = httpx.post(f'{BASE_URL}/piConnect', json=params, timeout=None)
            print(response)
            print(response.json())
            status = response.json()['status']
            print(f"Status: {status}")

            if status == "Command":
                print("do command things")
                commandFile = response.json()['scriptPath']
                commandFlags = response.json()['contentPath']
                wget.download(commandFile, out='/tmp/commandfile.py')
                try:
                    subprocess.Popen(["/usr/bin/python3", "/tmp/commandfile.py", f"--{commandFlags}"])
                except subprocess.CalledProcessError as e:
                    print(e, "probably unsupported TV")
                print(commandFlags, commandFile)

            elif status =="NoChange":
                print("I am sentient!")
                try:
                    tvStatus = str(tv.is_on())
                except OSError:
                    tvStatus = "UnsupportedTV"

            else:
                if status == "DEFAULT":
                    if tvStatusFlag:
                        print("turning tv off")
                        tv.standby()
                        tvStatusFlag = False
                        try:
                            tvStatus = str(tv.is_on())
                        except OSError:
                            tvStatus = "UnsupportedTV"
                else:
                    if not tvStatusFlag:
                        print("turning tv on")
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
                    print(chromePID.pid)
                else:
                    chromePID = startDisplay(controlFile, signageFile)
                    print(chromePID.pid)
                # chrome = startDisplay(signageFile)

            os.environ['DISPLAY'] = ':0'
            subprocess.run(["scrot", "-q", "5", "-t", "10", "-o", "-z", f"/tmp/{piName}.png"], 
                           check=True)

            data = {'piName': piName}
            files = {'file': open(f'/tmp/{piName}-thumb.png', 'rb')}
            r = httpx.post(f'{BASE_URL}/UploadPiScreenshot', data=data, files=files, timeout=None)

            print("I sleep...")
            time.sleep(30)
        except Exception as e:
            print ('type is:', e.__class__.__name__)
            print_exc()
            print("Caught a error...waiting and will try again")
            time.sleep(15)

if __name__ == "__main__":
    main()