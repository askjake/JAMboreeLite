#!/usr/bin/env python3
#
# send remote keys
#
# Usage
#  ./sgs_remote.py keyname [keyname...]
#   where 
#      - keyname - is a key to send to the STB
#      - -h      - prints all params
#
# Example
#   jamboree/sgs_remote.py Back Menu
#

from sgs_lib import *
import time
import argparse
import re
from key_lookup import lookup
from commands import get_button_number      # add near the other imports

SUPPORTED_KEYS = [
      "Power Toggle",
      "Power On",
      "Power Off (Not supported)",
      "Enter",
      "Cancel",
      "Guide",
      "Menu",
      "Home",
      "DVR",
      "Search",
      "Keypad",
      "Pause/Play",
      "Rewind",
      "Fast Forward",
      "Stop",
      "Skip Back",
      "Step Forward",
      "Format",
      "System Wizard",
      "Input",
      "Recover",
      "0","1","2","3","4","5","6","7","8","9","*","#",
      "Page Down",
      "Page Up",
      "Pause",
      "Play",
      "Record",
      "Blue",
      "Green",
      "Red",
      "Yellow",
      "Left",
      "Right",
      "Up",
      "Down",
      "Info",
      "Live TV",
      "Jump",
      "Recall",
      "PiP Toggle",
      "PiP Position",
      "PiP Swap",
      "DISH",
      "Sys Info",
      "Mode",
      "Mute",
      "Volume Down",
      "Volume Up"
      ]

# get params
parser = sgs_arg_parse(description="get Async events from receiver")
parser.add_argument("-t", "--time", help="time delay in ms between key-presses", default=200, type=int)
parser.add_argument("-l", "--list", help="list supported keys", action="store_true")
parser.add_argument("-f", "--logfile", help="read keys from im_key_log file", type=argparse.FileType('rb'))
#parser.add_argument("-f", "--logfile", help="read keys from im_key_log file", type=argparse.FileType('r', encoding="utf8", errors='ignore' ))
parser.add_argument("keys", help="list of keypresses to send to STB or 'tXX' for delay in XX ms", nargs='*')
args = parser.parse_args()

stb = STB(args)
# ------------------------------------------------------------------
# Detect if we were invoked with a single JSON payload (bridge mode)
if len(args.keys) == 1 and args.keys[0].startswith('{'):
    payload = json.loads(args.keys[0])
    print(json.dumps(payload))                 # keeps stdout for bridge
    result, _ = stb.sgs_command(payload)
    if not result or result.get("result") != 1:
        print("remote_key failed ->",
              json.dumps(result or {}, indent=2))
        sys.exit(1)
    sys.exit(0)


if args.list:
   print ("for delay use key format liek 'tXXX' where XXX is time in ms. i.e. t5000 for 5 second delay")
   print ("supported keys: \n", SUPPORTED_KEYS)
   exit()

default_delay = args.time/1000


def remote_key(key):
    data = {"command": "remote_key",
            "stb":      stb.stb,
            "tv_id":    "0",
            "key_name": key}
    result_data, _ = stb.sgs_command(data)

    if not result_data:
        print(" No response from STB")
        return

    if result_data.get("result") != 1:
        # Show entire reply for troubleshooting
        print("remote_key failed ->", json.dumps(result_data, indent=2))
    else:
        print("key accepted")

def send_key_any(button_name: str):
    """
    Convert a friendly button name ('enter', 'five', 'vol+') to the SGS
    numeric key_code using jamboree.commands, then send it via
    remote_key_automation (state 0 = toggle).
    """
    num = get_button_number(button_name)    # returns str or None
    if not num:
        print("Unsupported key:", button_name)
        return

    try:
        key_code = int(num)                 # '9' → 9
    except ValueError:
        print("Bad key_code in mapping for", button_name, "->", num)
        return

    cmd = {
        "command":  "remote_key_automation",
        "key_code": key_code,
        "state":    0           # 0 = press+release
    }

    resp, _ = stb.sgs_command(cmd)
    if not resp or resp.get("result") != 1:
        print("remote_key_automation failed ->",
              json.dumps(resp or {}, indent=2))
    else:
        print("key accepted")

# send 'remote_key_automation' command
def remote_key_automation(key, tv_id=0, state=0, data=None, device_id=None):
    if data is None:
        data = []

    cmd = {"command":  "remote_key_automation",
           "key_code": key}
    if tv_id:     cmd["tv_id"] = tv_id
    if state:     cmd["state"] = state
    if data:      cmd["data"]  = data
    if device_id: cmd["dev_id"] = device_id

    resp, _ = stb.sgs_command(cmd)

    if not resp:
        print(" No response from STB (automation)")
        return

    if resp.get("result") != 1:
        print("remote_key_automation failed ->", json.dumps(resp, indent=2))
    else:
        print("✓ automation accepted")

if not args.logfile:
   # go on main loop
   for key in args.keys:
      # handle 't100' keycode not as a key, but as a 'delay' command
      if key[0] == 't' and len(key)>1:
         delay = int(key[1:])/1000
         print (" sleep {:.2f} seconds".format(delay))
         time.sleep(delay)
      else:
         print (key)
         remote_key(key)
         time.sleep(default_delay)
else:
   # go through file (i.e. im_key_log)
   timestamp_old = 0
   linenum = 1
   time_last_sgs = time.time()
   for l in args.logfile.read().splitlines():
      a = l.split(b',')
      #print (a)
      if len(a) != 12:
         print ("unexpected format line", linenum, ":", a)
         exit()
      data = [0,0,0,0,0]
      timestamp = int(a[0])
      keycode = int(a[1])
      #tv = int(a[2])
      #remote_type = int(a[3])
      remote_device_id = int(a[4])
      state = int(a[5])
      data[4] = int(a[6])
      data[3] = int(a[7])
      data[2] = int(a[8])
      data[1] = int(a[9])
      data[0] = int(a[10])
      #fifo_handle = int(a[11])
      
      if timestamp <= 0:
         print ("unexpected timestamp at line", linenum, ":", timestamp)
         print (l)
         exit()
      # check timestamp
      if timestamp_old == 0:
         timestamp_old = timestamp
      else:
         sleeptime = timestamp - timestamp_old
         if sleeptime < 0:
            print ("time decreased unexpectedly at line", linenum, ":", timestamp)
            print (l)
            exit()
         # sleep between SGS commands (delay calculates based on timestamps from log)
         # note, the SGS command execution also takes time so we should take it into account when calculating required sleep delay
         sleep_delay = (sleeptime/1000) - (time.time()-time_last_sgs)
         if sleep_delay > 0:
            print ("                                 sleep {:.3f} seconds".format(sleep_delay))
            time.sleep(sleep_delay)
         timestamp_old = timestamp

      # support states except 'toggle'
      if state not in [0,1,2]:
         print ("unsupported state at line", linenum, ":", state)
         print (l)
         exit()

      time_last_sgs = time.time()

      if keycode in lookup.keys():
         print ("line {:3}: {:<19} - (timestamp {})".format(linenum, lookup[keycode], timestamp))
      else:
         print ("line {:3}: {:<19} - (timestamp {})".format(linenum, keycode, timestamp))
      remote_key_automation(keycode, state=state, data=data, device_id=remote_device_id)
      linenum += 1
