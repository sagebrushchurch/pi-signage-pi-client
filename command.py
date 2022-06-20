#!/usr/bin/python
import argparse
import os
import httpx

BASE_URL = 'https://pisignage.sagebrush.dev/pisignage_api'

parser = argparse.ArgumentParser(description="Pi Signage Command Script",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("-r", "--restart", action="store_true", help="reboot")
parser.add_argument("-c", "--content", action="store_true", help="re-download content")
parser.add_argument("-p", "--screenshot",action="store_true", help="update screenshot")
parser.add_argument("--tvon",action="store_true", help="turn tv on")
parser.add_argument("--tvoff",action="store_true", help="turn tv off")
args = parser.parse_args()
config = vars(args)

if config['restart']:
    os.system("sudo reboot")

if config['content']:
    print("re-downloading content")

if config['screenshot']:
    os.environ['DISPLAY'] = ':0'
    raspi2png = subprocess.run(["scrot", "-o", "-z", f"/tmp/{piName}.png"])
    
    data = {'piName': piName}
    files = {'file': open(f'/tmp/{piName}.png', 'rb')}
    r = await client.post(f'{BASE_URL}/UploadPiScreenshot', data=data, files=files)

if config['tvon']:
    print("trying to turn tv on")

if config['tvoff']:
    print("trying to turn tv off")