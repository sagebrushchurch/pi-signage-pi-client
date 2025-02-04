"""Pi Client Signage Code
Sends name and checksum to server and
server returns what content the pi should be displaying
"""
from traceback import print_exc
import subprocess
import datetime
import hashlib
import psutil
import httpx
import magic
import time
import wget
import gi
import os

gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

PI_NAME = os.uname()[1]
if '-dev-' in PI_NAME.lower():
    BASE_URL = 'https://piman.sagebrush.dev/pi_manager_api'
else:
        BASE_URL = 'https://piman.sagebrush.work/pi_manager_api'

PI_CLIENT_VERSION = '2.1.1'

DEVICE_MODEL = os.environ['DEVICE_MODEL']

browser = 'firefox'
browser_flags = '--kiosk'
logList = []
sessionType = ""

def clearFiles():
    """clears all temp files used for playback, ensures nothing is re-used"""
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
        recentLogs("Clearing files...")
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')

def md5checksum(fname):
    """checksum function to check media file being played back, sent to server to verify accuracy

    Args:
        fname (str): path to file to checksum

    Returns:
        str?: checksum of the file
    """
    md5 = hashlib.md5()

    # Handle content in binary form
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

# Define various pids
def avPID():
    pid = subprocess.Popen(["ffplay",
                            "-i",
                            "/tmp/signageFile",
                            "-loop",
                            "0",
                            "-fs",
                            "-fast"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Launching ffmpeg for audio/video file.")
    return pid

def linkPID():
    pid = subprocess.Popen([browser,
                            browser_flags,
                            "/tmp/signageFile"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Webpage detected. Launching Firefox.")
    return pid

def otherFilePID():
    pid = subprocess.Popen([browser,
                            browser_flags,
                            "/tmp/signageFile"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Undetermined file type. Attempting to launch in Firefox.")
    return pid

def startDisplay(controlFile, signageFile):
    """Starts firefox running the media content passed by signageFile
    and run using controlFile

    Args:
        controlFile (str): path to file that controls how media is played
        signageFile (str): path to media file

    Returns:
        PID: process object from spawning firefox
    """
    recentLogs("Downloading Signage File")
    wget.download(signageFile, out='/tmp/signageFile')
    if not controlFile == '':
        recentLogs("Downloading Control File.")
        wget.download(controlFile, out='/tmp/controlFile.html')
    try:
        fileType = magic.from_file(
            '/tmp/signageFile', mime=True)
        # recentLogs(f"File type '{fileType}' detected.") # For Debugging

        # Probably a video or audio file
        if 'video' in fileType or 'audio' in fileType:
            pid = avPID()

        # Probably a webpage
        elif 'html' in fileType:
            pid = linkPID()

        elif 'image' in fileType:
            pid = otherFilePID()

    # Probably something broke
        else:
            if controlFile == '':
                pid = otherFilePID()

        return pid

    except:
        recentLogs("Could not access signageFile")
        pass

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

    # Print to pi console for debugging
    print(str(datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")) + ' - ' + logMessage)
    return logList

def getIP():
    ipAddressInfo = subprocess.run(
        ['hostname',
         '-I'],
         stdout=subprocess.PIPE,
         check=True)
    ipAddress = ipAddressInfo.stdout.decode()

    return ipAddress

def getScreenResolution():
    resolution = subprocess.run(['/home/pi/pi-signage-pi-client/resolution.sh'],
        stdout=subprocess.PIPE).stdout.decode('utf-8')

    resolution = resolution.replace('\n', ' ')

    return resolution

def getLoadAverages():
    """gets the load averages from /proc/loadavg"""

    loadAvgFull = subprocess.run([
        'cat',
        '/proc/loadavg',
        ], stdout=subprocess.PIPE,
    )

    loadAvg = loadAvgFull.stdout.decode()

    return loadAvg

def getUptime():
    """gets the uptime from /proc/uptime"""

    uptimeFull = subprocess.run([
        'cat',
        '/proc/uptime',
    ], stdout=subprocess.PIPE,
    )

    uptime = uptimeFull.stdout.decode()

    return uptime

def main():
    """pisignage control, pings server to check content schedule, downloading new content when
    updated, downloads control scripts for running media on each update,
    uploads screenshot to server for dashboard monitoring.
    """

    recentLogs("Service Starting...")

    clearFiles()
    uptime = getUptime()
    browserPID = None
    ipAddress = getIP()
    loadAvg = getLoadAverages()
    loopDelayCounter = 0
    ScreenResolution = getScreenResolution()
    timeSinceLastConnection = 0
    previous_status = None
    default_hash = None

    os.environ['WAYLAND_DISPLAY'] = os.environ.get('WAYLAND_DISPLAY', 'wayland-1')
    os.environ['XDG_RUNTIME_DIR'] = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    lastConnectFlagDefault = False
    while True:
        if loopDelayCounter == 5:
            ipAddress = getIP()
            ScreenResolution = getScreenResolution()
            loopDelayCounter = 0
        loopDelayCounter += 1
        # Checks if signageFile exists first then checksums.
        # else 0.

        # first loop 0 since no files should exist
        if os.path.exists('/tmp/signageFile'):
            hash = md5checksum('/tmp/signageFile')
        else:
            hash = 0

        # Build data parameters for server post request
        parameters = {}
        piName = os.uname()[1]
        parameters["hash"] = hash
        parameters["load"] = loadAvg
        parameters["name"] = piName
        parameters["ipAddr"] = ipAddress
        parameters["piLogs"] = logList
        parameters["uptime"] = uptime
        parameters["hardware"] = DEVICE_MODEL
        parameters["screenRes"] = ScreenResolution
        parameters["clientVersion"] = PI_CLIENT_VERSION

        try:
            # timeout=None cuz in some cases the posts would time out.
            # Might need to change to 5 seconds if going too long causes a crash.
            response = httpx.post(
                f'{BASE_URL}/piConnect', json=parameters, timeout=5)

            # Check for status of 2XX in httpx response
            response.raise_for_status()

            status = response.json()['status']
            # Only log if status has changed
            if status != previous_status:
                recentLogs(f"Status: {status}")

            # Special case "command" keyword from scriptPath, causes pi to execute
            # command script using flags included in contentPath.
            if status == "Command":
                if status != previous_status:
                    recentLogs("do command things")
                commandFile = response.json()['scriptPath']
                commandFlags = response.json()['contentPath']
                if status != previous_status:
                    recentLogs(commandFlags)
                    recentLogs(commandFile)

            # We don't want the pi to update on every loop if content is the same.
            elif status == "NoChange":
                if status != previous_status:
                    recentLogs("No schedule change detected.")

            elif status == "DEFAULT":
                if status != previous_status:
                    recentLogs("Detected DEFAULT status.")
                    # Clear all files
                    clearFiles()
                    # Pull Default ONCE
                    signageFile = response.json()['contentPath']
                    wget.download(signageFile, out='/tmp/signageFile')
                    hash = md5checksum('/tmp/signageFile')
                    # Close the browser
                    if browserPID:
                        kill(browserPID.pid)

            else:
                # Clear all files before we download more.
                clearFiles()
                # Checking if firefox is active, it won't be after the first boot
                if browserPID:
                    kill(browserPID.pid)
                # Pull the paths of the files from the server response so we can download each
                controlFile = response.json()['scriptPath']
                signageFile = response.json()['contentPath']
                browserPID = startDisplay(controlFile, signageFile)
            # Take a screenshot of the display
            ssPath = f"/tmp/{piName}.png"
            try:
                subprocess.run(['grim',
                            ssPath],
                            capture_output=True,
                            text=True,
                            check=True)
            except subprocess.CalledProcessError as e:
                recentLogs(f"Error taking screenshot: {e}")
                recentLogs(f"Error output: {e.stderr}")
            # Build data object to upload screenshot to server
            data = {'piName': piName}
            files = {'file': open(ssPath, 'rb')}
            # timeout=None so it doesnt timeout for upload
            httpx.post(f'{BASE_URL}/UploadPiScreenshot',
                       data=data,
                       files=files,
                       timeout=None)
            # Main loop speed control
            time.sleep(30)

            previous_status = status

# Exceptions
        except httpx.HTTPError as http_exc:
            recentLogs(f"HTTP Error: {http_exc}")
            # # At each failed response add 1 attempt to the tally
            # # After 240 failed attempts (2 hours), reboot the pi
            # timeSinceLastConnection += 1
            # if timeSinceLastConnection >= 240:
            #     os.system('sudo reboot')
            # print(f"Unable to reach piman. Current tally is {timeSinceLastConnection}")
            # time.sleep(30)
        except psutil.NoSuchProcess:
            # Sometimes firefox's pid changes, I think it's cuz of the redirect for webpage viewing but
            # this catches it and another loop fixes it when it happens, so just loop again quickly
            time.sleep(1)
            recentLogs("firefox pid lost, restarting")
        except Exception as e:
            # General exception so that loop never crashes out, it will print it to the logs
            recentLogs('type is: ' + e.__class__.__name__)
            recentLogs(str(e))
            print_exc()
            recentLogs("Caught an error...waiting and will try again")
            # This timeout is if server is down or has minor issue, small delay to let it sort out
            time.sleep(15)

main()
