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
import re
# import gi
import os
import platform

# gi.require_version('Gdk', '3.0')
# from gi.repository import Gdk

PI_NAME = os.uname()[1]
if '-dev-' in PI_NAME.lower():
    BASE_URL = 'https://piman.sagebrush.dev/pi_manager_api'
else:
    BASE_URL = 'https://piman.sagebrush.work/pi_manager_api'

PI_CLIENT_VERSION = '2.8.3b'


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

def downloadFile(url, dest):
    """Download a file from url to dest using a streaming request with a timeout.
    Avoids hanging indefinitely on flaky networks, and handles large files without
    loading them fully into memory.

    Args:
        url (str): URL to download from
        dest (str): local file path to write to
    """
    with httpx.stream('GET', url, timeout=30, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_bytes():
                f.write(chunk)

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
def get_ffmpeg_version():
    """Get FFmpeg version to determine codec compatibility"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=5, check=False)
        version_line = result.stdout.split('\n')[0]
        # Extract version number (e.g., "ffmpeg version 7.1.2" -> "7.1.2")
        version_str = version_line.split()[2]
        major_version = int(version_str.split('.')[0])
        return major_version
    except (subprocess.TimeoutExpired, IndexError, ValueError, OSError):
        recentLogs("Could not detect FFmpeg version, assuming v5 compatibility")
        return 5

def get_video_codec():
    """Detect video codec of the file"""
    try:
        result = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                               '-show_entries', 'stream=codec_name', '-of', 
                               'csv=p=0', '/tmp/signageFile'], 
                              capture_output=True, text=True, timeout=5, check=False)
        codec = result.stdout.strip()
        return codec if codec else None
    except (subprocess.TimeoutExpired, OSError):
        recentLogs("Could not detect video codec, using default playback")
        return None

def avPID(is_audio=False):
    ffmpeg_version = get_ffmpeg_version()
    video_codec = get_video_codec()
    
    # Base ffplay command — audio-only files don't need a display
    if is_audio:
        cmd = ["ffplay", "-i", "/tmp/signageFile", "-loop", "0", "-nodisp"]
    else:
        cmd = ["ffplay", "-i", "/tmp/signageFile", "-loop", "0", "-fs", "-fast"]
    
    # For FFmpeg v7+, add hardware decoding if available
    if ffmpeg_version >= 7 and video_codec:
        if video_codec in ['h264']:
            # Use V4L2 M2M hardware decoder for H.264
            cmd.insert(1, "-c:v")
            cmd.insert(2, "h264_v4l2m2m")
            recentLogs(f"Using H.264 hardware decoding for FFmpeg v{ffmpeg_version}")
        elif video_codec in ['hevc', 'h265']:
            # Use V4L2 M2M hardware decoder for H.265/HEVC
            cmd.insert(1, "-c:v")
            cmd.insert(2, "hevc_v4l2m2m")
            recentLogs(f"Using H.265/HEVC hardware decoding for FFmpeg v{ffmpeg_version}")
        else:
            recentLogs(f"No hardware decoder available for codec {video_codec}, using software decoding")
    elif ffmpeg_version >= 7:
        recentLogs(f"FFmpeg v{ffmpeg_version} detected, but codec detection failed - using software decoding")
    else:
        recentLogs(f"FFmpeg v{ffmpeg_version} detected, using compatible software decoding")
    
    pid = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
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

def imagePID():
    pid = subprocess.Popen([browser,
                            browser_flags,
                            "/tmp/signageFile"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    recentLogs("Image detected. Launching Firefox.")
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
    downloadFile(signageFile, '/tmp/signageFile')
    if not controlFile == '':
        recentLogs("Downloading Control File.")
        downloadFile(controlFile, '/tmp/controlFile.html')
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
                
                if arch != 'x86_64' or ram < min_ram:
                    recentLogs(f"Skipping video: Arch={arch}, RAM={ram/(1024**3):.1f}GB. Need x86_64 & 4GB+. Showing fallback image.")
                    downloadFile('https://piman.sagebrush.work/pi_manager_api/media/Content_69eab3397e544073d0feeaae.jpg', '/tmp/signageFile')
                    pid = imagePID()
                    return pid
            pid = avPID(is_audio='audio' in fileType and 'video' not in fileType)

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
            else:
                # If controlFile is not empty, we still need to assign pid
                pid = otherFilePID()

        return pid

    except Exception as e:
        recentLogs(f"Could not access signageFile: {e}")
        return None

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
    """gets the uptime from /proc/uptime and returns a human-readable string"""

    uptimeFull = subprocess.run([
        'cat',
        '/proc/uptime',
    ], stdout=subprocess.PIPE,
    )

    uptime_seconds = float(uptimeFull.stdout.decode().split()[0])

    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    return ", ".join(parts)

SWAY_CONFIG_PATH = os.path.expanduser("~/.config/sway/config")

def set_sway_transform(value):
    """Persist an output transform in the Sway config file so it survives reboots.

    Replaces any existing 'output * transform' line, or appends one if absent.
    """
    line = f"output * transform {value}\n"
    pattern = re.compile(r"^\s*output\s+\*\s+transform\s+\S+.*$", re.MULTILINE)
    try:
        if os.path.exists(SWAY_CONFIG_PATH):
            with open(SWAY_CONFIG_PATH, "r") as f:
                contents = f.read()
            if pattern.search(contents):
                contents = pattern.sub(f"output * transform {value}", contents)
            else:
                contents += line
        else:
            os.makedirs(os.path.dirname(SWAY_CONFIG_PATH), exist_ok=True)
            contents = line
        with open(SWAY_CONFIG_PATH, "w") as f:
            f.write(contents)
    except OSError as e:
        recentLogs(f"Failed to update sway config: {e}")


def main():
    """pisignage control, pings server to check content schedule, downloading new content when
    updated, downloads control scripts for running media on each update,
    uploads screenshot to server for dashboard monitoring.
    """

    recentLogs("Service Starting...")

    clearFiles()
    browserPID = None
    ipAddress = getIP()
    loadAvg = getLoadAverages()
    loopDelayCounter = 0
    ScreenResolution = getScreenResolution()
    timeSinceLastConnection = 0
    networking_restarted = False
    previous_status = None
    default_hash = None

    os.environ['WAYLAND_DISPLAY'] = os.environ.get('WAYLAND_DISPLAY', 'wayland-1')
    os.environ['XDG_RUNTIME_DIR'] = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')

    while True:
        uptime = getUptime()
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
        parameters["os"] = OS_INFO

        try:
            # timeout=None cuz in some cases the posts would time out.
            # Might need to change to 5 seconds if going too long causes a crash.
            response = httpx.post(
                f'{BASE_URL}/piConnect', json=parameters, timeout=5)

            # Check for status of 2XX in httpx response
            response.raise_for_status()

            # Reset failure counter as soon as the main server connection is confirmed.
            # Keeping this here (not near the screenshot upload) means a failed
            # screenshot upload cannot falsely count as a server connection failure.
            timeSinceLastConnection = 0
            networking_restarted = False

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
                    recentLogs(f"Command Flags: {commandFlags}")
                    recentLogs(f"Command File: {commandFile}")
                # Execute command every loop, not just on status change
                if commandFlags == "Restart":
                    recentLogs("Rebooting...")
                    os.system("sudo reboot")
                elif commandFlags == "RestartProcess":
                    recentLogs("Restarting piman service...")
                    os.system("systemctl --user restart piman.service")
                elif commandFlags == "RotatePortraitLeft":
                    recentLogs("Rotating screen portrait left (270)...")
                    if os.system("swaymsg output '*' transform 270") == 0:
                        set_sway_transform(270)
                elif commandFlags == "RotatePortraitRight":
                    recentLogs("Rotating screen portrait right (90)...")
                    if os.system("swaymsg output '*' transform 90") == 0:
                        set_sway_transform(90)
                elif commandFlags == "RotateLandscape":
                    recentLogs("Rotating screen landscape (0)...")
                    if os.system("swaymsg output '*' transform 0") == 0:
                        set_sway_transform(0)

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
                    downloadFile(signageFile, '/tmp/signageFile')
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
            timeSinceLastConnection += 1
            # After 60 consecutive failed attempts (~30 min), restart networking once.
            # The >= check with a flag ensures this fires exactly once even if the
            # counter skips a value. This process (piman.service) keeps running after
            # the restart, so the counter continues to increment if not restored.
            if timeSinceLastConnection >= 60 and not networking_restarted:
                networking_restarted = True
                recentLogs("Lost connection for 30 minutes, restarting networking...")
                os.system('sudo systemctl restart networking')
            # After 120 consecutive failed attempts (~60 min), networking restart did
            # not restore connectivity — escalate to a full reboot.
            elif timeSinceLastConnection >= 120:
                recentLogs("Lost connection for 60 minutes, rebooting...")
                os.system('sudo reboot')
            print(f"Unable to reach piman. Current tally is {timeSinceLastConnection}")
            time.sleep(30)
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
