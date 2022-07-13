#!/usr/bin/python
import argparse
import os
import subprocess
import time
import httpx


BASE_URL = 'https://pisignage.sagebrush.dev/pisignage_api'

parser = argparse.ArgumentParser(description="Pi Signage Command Script",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("-r", "--Restart", action="store_true", help="reboots the pi")
parser.add_argument("-p", "--UploadScreenshot",action="store_true", help="update screenshot")
parser.add_argument("--TurnOnTV",action="store_true", help="turn tv on")
parser.add_argument("--TurnOffTV",action="store_true", help="turn tv off")
args = parser.parse_args()
config = vars(args)

if config['Restart']:
    os.system("sudo reboot")

if config['UploadScreenshot']:
    piName = os.uname()[1]
    os.environ['DISPLAY'] = ':0'
    raspi2png = subprocess.run(["scrot", "-q", "5", "-t", "10", "-o", "-z", f"/tmp/{piName}.png"], 
                               check=True)
    
    data = {'piName': piName}
    files = {'file': open(f'/tmp/{piName}.png', 'rb')}
    r = httpx.post(f'{BASE_URL}/UploadPiScreenshot', data=data, files=files)

if config['TurnOnTV']:
    echo = subprocess.Popen(('echo', 'on','0'), stdout=subprocess.PIPE)
    cec = subprocess.check_output(('cec-client', '-s', '-d', '1'), stdin=echo.stdout)
    echo.wait()
    time.sleep(10)
    echo = subprocess.Popen(('echo', 'as'), stdout=subprocess.PIPE)
    cec = subprocess.check_output(('cec-client', '-s', '-d', '1'), stdin=echo.stdout)
    echo.wait()

if config['TurnOffTV']:
    echo = subprocess.Popen(('echo', 'standby', '0'), stdout=subprocess.PIPE)
    cec = subprocess.check_output(('cec-client', '-s', '-d', '1'), stdin=echo.stdout)
    echo.wait()