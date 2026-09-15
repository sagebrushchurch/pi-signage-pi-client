"""Pi Client Signage Code
Sends name and checksum to server and
server returns what content the pi should be displaying
"""
from traceback import print_exc
from functools import lru_cache
import subprocess
import datetime
import hashlib
import psutil
import httpx
import magic
import time
import wget
# import gi
import os
import platform
import re

# gi.require_version('Gdk', '3.0')
# from gi.repository import Gdk

PI_NAME = os.uname()[1]
if '-dev-' in PI_NAME.lower():
    BASE_URL = 'https://piman.sagebrush.dev/pi_manager_api'
else:
    BASE_URL = 'https://piman.sagebrush.work/pi_manager_api'

PI_CLIENT_VERSION = '2.9.0'


def get_device_model():
    """Dynamically detect the device model.

    Detection order:
    1. /sys/firmware/devicetree/base/model  -- Raspberry Pi and many ARM SBCs
    2. 'Model' line in /proc/cpuinfo        -- Raspberry Pi fallback
    3. /sys/devices/virtual/dmi/id/product_name -- x86/x86_64 mini PCs via DMI
    4. Generic fallback using platform info
    """
    # Raspberry Pi / ARM SBC: device-tree model file
    dt_model_path = '/sys/firmware/devicetree/base/model'
    if os.path.exists(dt_model_path):
        try:
            with open(dt_model_path, 'r') as f:
                model = f.read().rstrip('\x00').strip()
            if model:
                return model
        except OSError:
            pass

    # Raspberry Pi fallback: 'Model' line in /proc/cpuinfo (capital M, text value)
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Model'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        model = parts[1].strip()
                        if model:
                            return model
    except OSError:
        pass

    # x86/x86_64 mini PCs: DMI product name
    dmi_path = '/sys/devices/virtual/dmi/id/product_name'
    if os.path.exists(dmi_path):
        try:
            with open(dmi_path, 'r') as f:
                model = f.read().strip()
            if model:
                return model
        except OSError:
            pass

    # Generic fallback
    return f"{platform.system()} {platform.machine()}"


DEVICE_MODEL = get_device_model()


def get_os_info():
    """Return a concise OS description, e.g. 'Debian 12' or 'Ubuntu 24.04'."""
    try:
        with open('/etc/os-release', 'r') as f:
            info = {}
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, _, value = line.partition('=')
                    info[key] = value.strip('"')
        name = info.get('NAME', '').replace('GNU/Linux', '').strip()
        version = info.get('VERSION_ID', '')
        if name and version:
            return f"{name} {version}"
        elif name:
            return name
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}"


OS_INFO = get_os_info()

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
    """Launch mpv for audio/video playback with hardware acceleration where available.

    Hardware decoder selection:
      - x86_64 : --hwdec=auto  (tries vaapi, nvdec, vdpau, etc. in order)
      - aarch64 / armv7l (Raspberry Pi 4/5): --hwdec=v4l2m2m
      - anything else: software decoding
    """
    arch = platform.machine()

    cmd = [
        "mpv",
        "--loop=inf",
        "--fs",
        "--no-border",
        "--osd-level=0",
        "--no-terminal",
    ]

    if arch == 'x86_64':
        cmd.append("--hwdec=auto")
        recentLogs("Using auto hardware decoding for x86_64")
    elif arch in ('aarch64', 'armv7l'):
        cmd.append("--hwdec=v4l2m2m")
        recentLogs("Using V4L2 M2M hardware decoding for ARM")
    else:
        cmd.append("--hwdec=no")
        recentLogs(f"Unknown arch {arch}, using software decoding")

    cmd.append("/tmp/signageFile")

    pid = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    recentLogs("Launching mpv for audio/video file.")
    return pid

def linkPID():
    pid = subprocess.Popen([browser,
                            browser_flags,
                            "/tmp/signageFile"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Webpage detected. Launching Firefox.")
    return pid

def imagePID():
    pid = subprocess.Popen([
                            "mpv",
                            "--fs",
                            "--no-border",
                            "--osd-level=0",
                            "--no-terminal",
                            "--image-display-duration=inf",
                            "/tmp/signageFile"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Image detected. Launching mpv.")
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
    """Starts the appropriate player for the media content passed by signageFile.
    Videos and audio use mpv, still images use mpv with --image-display-duration=inf,
    and webpages use firefox.

    Args:
        controlFile (str): path to file that controls how media is played
        signageFile (str): path to media file

    Returns:
        PID: process object from spawning the player
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
            if 'video' in fileType:
                arch = platform.machine()
                # 3.8GB in bytes to account for system reserved memory on 4GB modules
                min_ram = 3.8 * 1024 * 1024 * 1024
                ram = psutil.virtual_memory().total
                # Capable devices: x86_64 with ≥4 GB RAM, or Raspberry Pi 4/5
                # (Pi 4/5 have hardware video decoders; Pi 3 and earlier are too slow)
                # DEVICE_MODEL contains the full model string (e.g. "Raspberry Pi 4 Model B"),
                # so substring matching with 'in' intentionally catches all Pi 4/5 variants.
                # RAM is not gated for Pi 4/5 because mpv's V4L2 M2M hardware decoder
                # uses very little system memory even on 1 GB configurations.
                is_capable_x86 = (arch == 'x86_64' and ram >= min_ram)
                is_pi4_or_newer = (
                    'Raspberry Pi 4' in DEVICE_MODEL or
                    'Raspberry Pi 5' in DEVICE_MODEL
                )

                if not (is_capable_x86 or is_pi4_or_newer):
                    recentLogs(
                        f"Skipping video: Device={DEVICE_MODEL}, "
                        f"Arch={arch}, RAM={ram/(1024**3):.1f}GB. "
                        f"Need x86_64 with {min_ram/(1024**3):.1f}GB RAM or Raspberry Pi 4/5."
                    )
                    return None
            pid = avPID()

        # Probably a webpage
        elif 'html' in fileType:
            pid = linkPID()

        # Probably a picture
        elif 'image' in fileType:
            pid = imagePID()

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
    """gets the system uptime and returns it as a human-readable string, e.g. '2 days, 3 hours, 15 minutes'"""

    uptimeFull = subprocess.run([
        'cat',
        '/proc/uptime',
    ], stdout=subprocess.PIPE,
    )

    # First value is uptime in seconds, second is idle time; we only need uptime.
    uptimeSeconds = int(float(uptimeFull.stdout.decode().split()[0]))

    days, remainder = divmod(uptimeSeconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    return ', '.join(parts)

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
                commandFile = response.json()['scriptPath']
                commandFlags = response.json()['contentPath']
                if status != previous_status:
                    recentLogs("do command things")
                    if commandFlags == "Restart":
                        os.system("sudo reboot")
                if status != previous_status:
                    recentLogs(f"Command Flags: {commandFlags}")
                    recentLogs(f"Command File: {commandFile}")

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
            screenshot_taken = False
            try:
                subprocess.run(['grim',
                            ssPath],
                            capture_output=True,
                            text=True,
                            check=True)
                screenshot_taken = True
            except subprocess.CalledProcessError as e:
                recentLogs(f"Error taking screenshot: {e}")
                recentLogs(f"Error output: {e.stderr}")
            # Only upload screenshot if grim succeeded
            if screenshot_taken:
                data = {'piName': piName}
                with open(ssPath, 'rb') as ssFile:
                    files = {'file': ssFile}
                    # Longer timeout for image file upload
                    httpx.post(f'{BASE_URL}/UploadPiScreenshot',
                               data=data,
                               files=files,
                               timeout=10)
            # Main loop speed control
            time.sleep(30)

            previous_status = status

# Exceptions
        except httpx.HTTPError as http_exc:
            recentLogs(f"HTTP Error: {http_exc}")
            print(f"HTTP Error: {http_exc}")
            # # At each failed response add 1 attempt to the tally
            # # After 60 failed attempts (0.5 hours), restart networking and piman service
            timeSinceLastConnection += 1
            if timeSinceLastConnection >= 60:
                os.system('sudo systemctl restart networking && systemctl --user restart piman.service ')
            print(f"Unable to reach piman. Current tally is {timeSinceLastConnection}")
            time.sleep(30)
        except psutil.NoSuchProcess:
            # Sometimes the player's pid changes (e.g. firefox redirects for webpage viewing)
            # this catches it and another loop fixes it when it happens, so just loop again quickly
            time.sleep(1)
            recentLogs("player pid lost, restarting")
        except Exception as e:
            # General exception so that loop never crashes out, it will print it to the logs
            recentLogs('type is: ' + e.__class__.__name__)
            recentLogs(str(e))
            print_exc()
            recentLogs("Caught an error...waiting and will try again")
            # This timeout is if server is down or has minor issue, small delay to let it sort out
            time.sleep(15)

main()
