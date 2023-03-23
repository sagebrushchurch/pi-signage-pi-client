"""Pi Client Signage Code
Sends name and checksum to server and
server returns what content the pi should be displaying
"""
from traceback import print_exc
import os
import hashlib
import subprocess
import time
import datetime
import psutil
import httpx
import wget
import magic

if os.path.exists('/dev/vchiq'):
    import cec
    cecType = 'raspi'
elif os.path.exists('/dev/cec0'):
    cecType = 'other'
else:
    cecType = 'none'
    print("No CEC device detected")



PI_CLIENT_VERSION = '1.4.0'
# BASE_URL = 'https://piman.sagebrush.dev/pi_manager_api'
BASE_URL = 'https://piman.sagebrush.work/pi_manager_api'
logList = []


def clearFiles():
    """clears all temp files used for playback, ensures nothing is re-used"""
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
    if os.path.exists('/tmp/webPage.html'):
        os.remove('/tmp/webPage.html')
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')


def md5checksum(fname):
    """checksuming function to check media file being played back, sent to server to verify accuracy

    Args:
        fname (str): path to file to checksum

    Returns:
        str?: checksum of the file
    """
    md5 = hashlib.md5()

    # handle content in binary form
    f = open(fname, "rb")
    while chunk := f.read(4096):
        md5.update(chunk)

    return md5.hexdigest()


def kill(proc_pid):
    """Used to stop running process by ID

    Args:
        proc_pid (int?): the process ID
    """
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def startDisplay(controlFile, signageFile):
    """Starts chrome running the media content passed by signageFile
    and run using controlFile

    Args:
        controlFile (str): path to file that controls how media is played
        signageFile (str): path to media file

    Returns:
        PID: process object from spawning chrome
    """
    clearFiles()
    # output the files to /tmp so they would get purged on a reboot
    wget.download(signageFile, out='/tmp/signageFile')
    if not controlFile == '':
        wget.download(controlFile, out='/tmp/controlFile.html')
    # have to set the environment var for the display so chrome knows where to output
    os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
    os.environ['DISPLAY'] = ':0'
    # pop open the chrome process so main loop doesnt wait, dump its ouput to null cuz its messy
    try:
        fileType = magic.from_file(
            '/tmp/signageFile', mime=True)
        print(fileType)
    except:
        recentLogs("failed to read file type")
        pass

    if 'video' in fileType:
        pid = subprocess.Popen(["cvlc",
                                "--video-wallpaper",
                                "--no-osd",
                                "mouse-hide-timeout",
                                "1",
                                "-L",
                                "/tmp/signageFile"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.STDOUT)
        print("video file")
        
    elif 'audio' in fileType:
        pid = subprocess.Popen(["cvlc",
                                "--video-wallpaper",
                                "--no-osd",
                                "mouse-hide-timeout",
                                "1",
                                "-L",
                                "/tmp/signageFile"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.STDOUT)
        print("audio file")
    else:
        if not controlFile == '':
            pid = subprocess.Popen(["chromium-browser", "--enable-features=WebContentsForceDark",
                                    "--kiosk",
                                    "--autoplay-policy=no-user-gesture-required",
                                    "/tmp/controlFile.html"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        else:
            recentLogs('Control File Missing')
    return pid


def startWebDisplay(signageFile):
    """Starts chrome running the website passed by signageFile

    Args:
        signageFile (str): html file with site redirect

    Returns:
        PID: process object from spawning pid
    """
    clearFiles()
    # output the file to /tmp so it would get purged on a reboot
    wget.download(signageFile, out='/tmp/webPage.html')
    # have to set the environment var for the display so chrome knows where to output
    os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
    os.environ['DISPLAY'] = ':0'
    # pop open the chrome process so main loop doesnt wait, dump its ouput to null cuz its messy
    pid2 = subprocess.Popen(["chromium-browser", "--kiosk",
                             "--autoplay-policy=no-user-gesture-required",
                             "/tmp/webPage.html"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return pid2


def recentLogs(logMessage: str):
    """keeps track of the previous 50 debug messages for sending to server

    Args:
        logMessage (str): the log message

    Returns:
        list: list of log messages
    """
    if len(logList) > 50:
        logList.pop(0)
    logList.append(str(datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")) + ' - ' + logMessage)

    # print to pi console for debug
    print(str(datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")) + ' - ' + logMessage)
    return logList


def getIP():

    ipAddrInfo = subprocess.run(
        ['hostname', '-I'], stdout=subprocess.PIPE, check=True)
    ipAddrs = ipAddrInfo.stdout.decode()

    return ipAddrs


def getScreenRes():
    try:
        screenInfo = subprocess.run(
            ['xrandr', '--display', ':0'], stdout=subprocess.PIPE, check=True)
        screenSplit = screenInfo.stdout.decode().split()
        # screenRes = screenSplit[1].replace('"', '')
        screenRes = screenSplit[7] + screenSplit[8] + \
            screenSplit[9].replace(',', '')
    except subprocess.CalledProcessError:
        screenRes = "No Screen Attached"

    return screenRes

def getPowerStateCecCtl(data):
    lines = str(data).split('\\n\\t')
    for line in lines:
        if 'pwr-state' in line:
            state = line.split(':')[-1].strip()
            rawState = state.split()[0]
            if rawState == 'standby':
                return 'False'
            elif rawState == 'on':
                return 'True'
            else:
                return rawState
    return 'Unknown'


def main():
    """pisignage control, pings server to check content schedule, downloading new content when
    updated, downloads control scripts for running media on each update,
    uploads screenshot to server for dashboard monitoring.
    """
    if cecType == 'raspi':
        cec.init()
        tv = cec.Device(cec.CECDEVICE_TV)
    elif cecType == 'other':
        subprocess.Popen(["/usr/bin/cec-ctl", "--tv", "-S"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.STDOUT)
    clearFiles()
    chromePID = None
    tvStatusFlag = False
    tvStatus = "False"
    loopDelayCounter = 0
    ipAddrs = getIP()
    screenRes = getScreenRes()

    while True:
        if loopDelayCounter == 5:
            ipAddrs = getIP()
            screenRes = getScreenRes()
            loopDelayCounter = 0
        loopDelayCounter += 1

        recentLogs("TV Power Status: " + tvStatus)
    # checks if signageFile exists first then checksums, if not checksum the webpage file, else 0
        # first loop 0 since no files should exist
        if os.path.exists('/tmp/signageFile'):
            hash = md5checksum('/tmp/signageFile')
        elif os.path.exists('/tmp/webPage.html'):
            hash = md5checksum('/tmp/webPage.html')
        else:
            hash = 0
        # build data params for server post request
        params = {}
        piName = os.uname()[1]
        params["name"] = piName
        params["hash"] = hash
        params["tvStatus"] = tvStatus
        params["piLogs"] = logList
        params["ipAddr"] = ipAddrs
        params["screenRes"] = screenRes
        params["clientVersion"] = PI_CLIENT_VERSION

        try:
            # did timeout=None cuz in some cases the posts would time out, might need to change to
            # 5 seconds if going too long causes crash
            response = httpx.post(
                f'{BASE_URL}/piConnect', json=params, timeout=None)
            status = response.json()['status']
            recentLogs(f"Status: {status}")
            # special case "command" keyword, from scriptPath, causes pi to execute command script
            # using flags included in contentPath.
            if status == "Command":
                recentLogs("do command things")
                commandFile = response.json()['scriptPath']
                commandFlags = response.json()['contentPath']
                recentLogs(commandFlags)
                if commandFlags == 'TurnOffTV':
                    if cecType == 'raspi':
                        tv.standby()
                    elif cecType == 'other':
                        subprocess.Popen(["/usr/bin/cec-ctl", "--to", "0", "--standby"],
                                         stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)

                elif commandFlags == 'TurnOnTV':
                    if cecType == 'raspi':
                        tv.power_on()
                    elif cecType == 'other':
                        subprocess.Popen(["/usr/bin/cec-ctl", "--to", "0", "--image-view-on"],
                                         stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)

                else:
                    wget.download(commandFile, out='/tmp/commandfile.py')
                    try:
                        subprocess.Popen(
                            ["/usr/bin/python3", "/tmp/commandfile.py", f"--{commandFlags}"])
                    # sometimes tvon/off will throw an error cuz cec is a mess, so just in case
                    except subprocess.CalledProcessError as e:
                        recentLogs(str(e))
                        recentLogs("probably unsupported TV")
                recentLogs(commandFlags)
                recentLogs(commandFile)
            # dont want the pi to update on every loop if content is the same, checks tv status on
            # each loop for dashboard updating
            elif status == "NoChange":
                recentLogs("I am sentient!")
                try:
                    if cecType == 'raspi':
                        tvStatus = str(tv.is_on())
                    elif cecType == 'other':
                      cecStatus = subprocess.run(["/usr/bin/cec-ctl",
                                                                "--to", "0",
                                                                "--give-device-power-status"],
                                                                check=True, capture_output=True)
                      tvStatus = getPowerStateCecCtl(cecStatus.stdout)
                # not all displays support cec, catching unsupported tv error
                except OSError as e:
                    recentLogs(str(e))
                    tvStatus = "UnsupportedTV"
            # if not Command or NoChange, this is for actual content updating
            else:
                # We check for DEFAULT keyword to use as a trigger to turn tv off since its probably
                # done for the day when default content is live
                if status == "DEFAULT":
                    if tvStatusFlag:
                        recentLogs("turning tv off")
                        if cecType == 'raspi':
                            tv.standby()
                        elif cecType == 'other':
                            subprocess.Popen(["/usr/bin/cec-ctl", "--to", "0", "--standby"],
                                             stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
                        tvStatusFlag = False
                        try:
                            if cecType == 'raspi':
                                tvStatus = str(tv.is_on())
                            elif cecType == 'other':
                                cecStatus = subprocess.run(["/usr/bin/cec-ctl",
                                                            "--to", "0",
                                                            "--give-device-power-status"],
                                                            check=True, capture_output=True)
                                tvStatus = getPowerStateCecCtl(cecStatus.stdout)
                        except OSError as e:
                            recentLogs(str(e))
                            tvStatus = "UnsupportedTV"
                else:
                    if not tvStatusFlag:
                        recentLogs("turning tv on")
                        if cecType == 'raspi':
                            tv.power_on()
                        elif cecType == 'other':
                            subprocess.Popen(["/usr/bin/cec-ctl", "--to", "0", "--image-view-on"],
                                             stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
                        tvStatusFlag = True
                        try:
                            if cecType == 'raspi':
                                tvStatus = str(tv.is_on())
                            elif cecType =='other':
                                tvStatus = getPowerStateCecCtl(subprocess.run(["/usr/bin/cec-ctl",
                                                                "--to", "0",
                                                                "--give-device-power-status"],
                                                                check=True, stdout=subprocess.PIPE))
                        except OSError as e:
                            recentLogs(str(e))
                            tvStatus = "UnsupportedTV"
                # clear all files before we download more, we need to check if controlFile exists
                # to determine if we the pi needs to display a webpage or other media
                clearFiles()
                # checking if chrome is active, wont be for first boot
                if chromePID:
                    kill(chromePID.pid)
                # pull the paths of the files from the server response so we can download each
                controlFile = response.json()['scriptPath']
                signageFile = response.json()['contentPath']
                if controlFile == '' and signageFile.endswith('.html'):
                    chromePID = startWebDisplay(signageFile)
                else:
                    chromePID = startDisplay(controlFile, signageFile)
            # have to set display for screenshot, might be dup but its fine
            os.environ['DISPLAY'] = ':0'
            # take a screenshot of the display, sets the quality low and makes a thumbnail
            subprocess.run(["scrot", "-q", "5", "-t", "10", "-o", "-z", f"/tmp/{piName}.png"],
                           check=True)
            # build data object to upload screenshot to server
            data = {'piName': piName}
            # upload -thumb file so its smol
            files = {'file': open(f'/tmp/{piName}-thumb.png', 'rb')}
            # timeout=None so it doesnt timeout for upload or whatever
            httpx.post(f'{BASE_URL}/UploadPiScreenshot',
                       data=data, files=files, timeout=None)
            recentLogs("I sleep...")
            # main loop speed control
            time.sleep(30)
        except psutil.NoSuchProcess:
            # Sometimes chrome's pid changes, i think its cuz of the redirect for webpage viewing
        # but this catches it and another loop fixes it when it happens, so just loop again quickly
            time.sleep(1)
            recentLogs("chrome pid lost, restarting")
        except Exception as e:
            # general exception so that loop never crashes out, it will print it to the logs
            recentLogs('type is: ' + e.__class__.__name__)
            recentLogs(str(e))
            print_exc()
            recentLogs("Caught a error...waiting and will try again")
            # this timeout is if server is down or has minor issue, small delay to let it sort out
            time.sleep(15)


if __name__ == "__main__":
    main()
