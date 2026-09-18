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
import socket
import time
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

PI_CLIENT_VERSION = '2.10.0'


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

browser = 'firefox'
browser_flags = '--kiosk'
logList = []

def clearFiles():
    """clears all temp files used for playback, ensures nothing is re-used"""
    if os.path.exists('/tmp/signageFile'):
        os.remove('/tmp/signageFile')
        recentLogs("Clearing files...")
    if os.path.exists('/tmp/controlFile.html'):
        os.remove('/tmp/controlFile.html')

def download_file(url, dest, timeout=15):
    """Download url to dest with a bounded timeout so a network stall can't hang the process forever.
    Removes any partially written file on failure so a stale/corrupt file is never left behind.

    Args:
        url (str): file to download
        dest (str): local path to write to
        timeout (int): seconds to allow for the whole request/download
    """
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
    except Exception:
        if os.path.exists(dest):
            os.remove(dest)
        raise

def sd_notify(state: str):
    """Send a message to systemd's sd_notify socket (readiness/watchdog); no-op if not running under systemd."""
    addr = os.environ.get('NOTIFY_SOCKET')
    if not addr:
        return
    if addr.startswith('@'):
        addr = '\0' + addr[1:]
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(addr)
        sock.sendall(state.encode())
    except OSError:
        pass
    finally:
        if sock:
            sock.close()

def md5checksum(fname):
    """checksum function to check media file being played back, sent to server to verify accuracy

    Args:
        fname (str): path to file to checksum

    Returns:
        str?: checksum of the file
    """
    md5 = hashlib.md5()

    # Handle content in binary form
    with open(fname, "rb") as f:
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
    download_file(signageFile, '/tmp/signageFile')
    if not controlFile == '':
        recentLogs("Downloading Control File.")
        download_file(controlFile, '/tmp/controlFile.html')
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
            pid = otherFilePID() if controlFile == '' else None

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
    try:
        ipAddressInfo = subprocess.run(
            ['hostname',
             '-I'],
             stdout=subprocess.PIPE,
             check=True)
        ipAddress = ipAddressInfo.stdout.decode()
    except (subprocess.CalledProcessError, OSError):
        return ''

    return ipAddress

def getScreenResolution():
    try:
        resolution = subprocess.run(['/home/pi/pi-signage-pi-client/resolution.sh'],
            stdout=subprocess.PIPE, timeout=5).stdout.decode('utf-8')
    except (subprocess.TimeoutExpired, OSError):
        return ''

    resolution = resolution.replace('\n', ' ')

    return resolution

def getLoadAverages():
    """gets the load averages from /proc/loadavg"""
    try:
        with open('/proc/loadavg', 'r') as f:
            return f.read()
    except OSError:
        return ''

def getUptime():
    """gets the system uptime and returns it as a human-readable string, e.g. '2 days, 3 hours, 15 minutes'"""

    with open('/proc/uptime', 'r') as f:
        uptimeContents = f.read()

    # First value is uptime in seconds, second is idle time; we only need uptime.
    uptimeSeconds = int(float(uptimeContents.split()[0]))

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

    os.environ['WAYLAND_DISPLAY'] = os.environ.get('WAYLAND_DISPLAY', 'wayland-1')
    os.environ['XDG_RUNTIME_DIR'] = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    sd_notify('READY=1')
    while True:
        # Tells systemd's watchdog we're still alive; only reached once the previous
        # iteration's bounded network/subprocess calls have returned.
        sd_notify('WATCHDOG=1')
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
        piName = PI_NAME
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
            response = httpx.post(
                f'{BASE_URL}/piConnect', json=parameters, timeout=5)

            # Check for status of 2XX in httpx response
            response.raise_for_status()

            status = response.json()['status']
            # Only log if status has changed
            if status != previous_status:
                recentLogs(f"Status: {status}")

            # We don't want the pi to update on every loop if content is the same.
            if status == "NoChange":
                if status != previous_status:
                    recentLogs("No schedule change detected.")

            elif status == "DEFAULT":
                if status != previous_status:
                    recentLogs("Detected DEFAULT status.")
                    # Clear all files
                    clearFiles()
                    # Pull Default ONCE
                    signageFile = response.json()['contentPath']
                    download_file(signageFile, '/tmp/signageFile')
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
                            timeout=10,
                            check=True)
                screenshot_taken = True
            except subprocess.CalledProcessError as e:
                recentLogs(f"Error taking screenshot: {e}")
                recentLogs(f"Error output: {e.stderr}")
            except subprocess.TimeoutExpired:
                recentLogs("Timed out taking screenshot")
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
                subprocess.run(['sudo', 'systemctl', 'restart', 'networking'])
                subprocess.run(['systemctl', '--user', 'restart', 'piman.service'])
                timeSinceLastConnection = 0
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
