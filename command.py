import argparse

parser = argparse.ArgumentParser(description="Pi Signage Command Script",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("-s", "--shutdown", action="store_true", help="shutdown")
parser.add_argument("-r", "--restart", action="store_true", help="reboot")
parser.add_argument("-c", "--content", action="store_true", help="re-download content")
parser.add_argument("-p", "--screenshot",action="store_true", help="update screenshot")
