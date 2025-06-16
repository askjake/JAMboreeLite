#!/usr/bin/env python3
#
# SGS related functions
#
# Content:
#   class STB - the base class to interact with STB
#   STB::sgs_command() - sends SGS command to STB (using secure or unsecure protocol depending on STB type)
#   STB::__init__ - for prod boxes actually perform pairing (if not done previously) and attach
#   sgs_arg_parse() - parse base arguments needed for STB
#
# example usage:
#      parser = sgs_arg_parse(description="example")
#      args = parser.parse_args()
#      stb = STB(args)
#      resp = stb.sgs_command ({"command":"example"})
#      if resp: print (json.dumps(resp))


import sys
import json
import os
import socket
import struct
import argparse
import requests
import logging
from uuid import getnode as get_mac
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent  # ← canonical base.txt location
PROJECT_ROOT = PACKAGE_DIR.parent
BASE_FILE    = PROJECT_ROOT / "base.txt"

# disable insecure request warning on recent Python
if sys.version_info >= (3, 6):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Attempt to import fcntl (only on Unix)
try:
    import fcntl
except ImportError:
    fcntl = None
    logging.debug("fcntl not available; skipping Unix-only network interface helpers")

DEFAULT_PC_IP_PATTERN = "192.168.1"
DEFAULT_STB_PORT       = 8080
DEFAULT_CID            = 1004
DEFAULT_RECEIVER       = "R0000000000-00"

from typing import Dict, Any

def resolve_sgs_ip(alias: str, cfg: Dict[str, Any]) -> str:
    """
    Return the IP that should receive an SGS request for `alias`.
    For Joeys we proxy through their host Hopper.
    """
    rec = cfg["stbs"][alias]

    if rec.get("role") == "joey" and rec.get("host"):
        host_alias = rec["host"]
        host_rec   = cfg["stbs"].get(host_alias)
        if host_rec and host_rec.get("ip"):
            return host_rec["ip"]

    # default: talk to the device itself
    return rec["ip"]

def get_ip_address(ifname: str) -> str:
    """Return the IPv4 address for interface `ifname` (Unix only)."""
    if not fcntl:
        logging.warning("get_ip_address: fcntl unavailable on this platform")
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    name = bytearray(ifname[:15], 'utf-8')
    try:
        packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', name))
        return socket.inet_ntoa(packed[20:24])
    except Exception as e:
        logging.error("cannot get IP for %s: %s", ifname, e)
        return ""


def getHwAddr(ifname: str) -> str:
    """Return the MAC address for interface `ifname` (Unix only)."""
    if not fcntl:
        logging.warning("getHwAddr: fcntl unavailable on this platform")
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    name = bytearray(ifname[:15], 'utf-8')
    try:
        info = fcntl.ioctl(s.fileno(), 0x8927, struct.pack('256s', name))
        return ''.join(f"{b:02x}" for b in info[18:24])
    except Exception as e:
        logging.error("cannot get mac for %s: %s", ifname, e)
        return ""


def get_local_iface_mac(addr_pattern: str = DEFAULT_PC_IP_PATTERN) -> str:
    """
    Return the PC's primary MAC (as hex string).
    Falls back to scanning /sys/class/net on Unix if needed.
    """
    # primary fallback: Python's uuid.getnode()
    mac = get_mac()
    if mac and (mac >> 40) & 0xff != 0x00:
        return ''.join(f"{(mac >> i) & 0xff:02x}" for i in range(0, 48, 8)[::-1])
    # Unix fallback by interface name
    if fcntl:
        for ifname in os.listdir('/sys/class/net/'):
            ip = get_ip_address(ifname)
            if addr_pattern in ip:
                return getHwAddr(ifname)
    return ""


def sgs_get_receiver_id() -> str:
    """
    Build a receiver ID string based on local MAC.
    Format: 'XAF' + <lowercase mac without separators>
    """
    mac = get_local_iface_mac()
    if mac:
        return f"XAF{mac}"
    logging.warning("Falling back to default receiver %s", DEFAULT_RECEIVER)
    return DEFAULT_RECEIVER


def sgs_save_base(base: dict, path: Path = BASE_FILE) -> None:
   """
   Write `base` JSON to project-root/base.txt.
   """
   logging.debug("Saving base file to %s", path)
   try:
      path.parent.mkdir(parents=True, exist_ok=True)
      with path.open("w", encoding="utf-8") as out:
         json.dump(base, out, indent=2)
      logging.info("Saved base config to %s", path)
   except Exception:
      logging.exception("Failed to save base config to %s", path)
      raise


def sgs_load_base(path: Path = BASE_FILE) -> dict:
   """
   Load STB configuration from project-root/base.txt.
   Raises FileNotFoundError if not present.
   """
   logging.debug("Attempting to load base file from %s", path)
   if not path.is_file():
      msg = f"base file not found at {path}"
      logging.error(msg)
      raise FileNotFoundError(msg)

   try:
      with path.open("r", encoding="utf-8") as f:
         base = json.load(f)
      cnt = len(base.get("stbs", {}))
      logging.info("Loaded base config (%d STBs) from %s", cnt, path)
      return base
   except Exception:
      logging.exception("Error parsing base file %s", path)
      raise

from .stb_store import store

def resolve_sgs_ip(alias: str) -> str:
    """
    Return the IP that should receive an SGS request for `alias`.
    • Joey  → Hopper’s IP   (proxy)
    • Hopper → its own IP
    """
    rec = store.get(alias)
    if not rec:
        raise KeyError(f"Unknown alias '{alias}' in store")

    if rec.get("role", "").lower() == "joey":
        host_alias = rec.get("host")
        host_rec   = store.get(host_alias or "")
        if not host_rec:
            raise KeyError(f"Joey '{alias}' references unknown host '{host_alias}'")
        return host_rec["ip"]

    return rec["ip"]

# configure arguments parser - add common params that are applicable for any SGS
def sgs_arg_parse (description, epilog=None):
   parser = argparse.ArgumentParser(description=description, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
   parser.add_argument("-n", "--name", help="read STB info from base.txt file by name")
   parser.add_argument("-s", "--stb", help="specify STB receiver ID")
   parser.add_argument("-i", "--ip", help="specify STB IP")
   parser.add_argument("-p", "--port", help="specify STB port")
   parser.add_argument("-v", "--verbose", help="print SGS queries and responses", action="store_true")
   parser.add_argument("-o", "--prod", help="if it is a production STB (if not set then dev)", action="store_true")
   parser.add_argument("-L", "--login", help="(for production STBs) login for HTTPs")
   parser.add_argument("-P", "--passwd", help="(for production STBs) passwd for HTTPs")
   return parser

AE_EVENTS_NAMES = [
"AE_INVALID",
"AE_TUNER_STATUS",
"AE_DVR_SIGNAL_LOSS",
"AE_EVT_TRANSITION",
"AE_CHANNEL_CHANGE_STATUS",
"AE_REMOTE_CHANNEL_CHANGING",
"AE_VIEW_SHARING_STATUS",
"AE_TIMER_CREATION_STATUS",
"AE_SLING_SERVER_CONN_REQ",
"AE_EPG_UPDATED",
"AE_SDT_UPDATED",
"AE_SAT_TIME_INFO",
"AE_SAT_SIGNAL_STRENGTH",
"AE_CHECK_SWITCH_STATUS",
"AE_SAT_NAME_LIST_UPDATED",
"AE_PLAY_STATUS_CHANGED",
"AE_CALLER_ID",
"AE_DIAL_OUT_STATUS",
"AE_CONNECTION_TEST_STATUS",
"AE_PURCHASE_STATUS",
"AE_PARENTAL_CONTROL_COPY",
"AE_TUNER_USAGE_UPDATE",
"AE_TIMER_WARNING",
"AE_TIMER_CONFLICT_STATUS_UPDATE",
"AE_TIMER_DEL_STATUS",
"AE_MUSIC_TITLE_UPDATE",
"AE_SYSTEM_BUSY",
"AE_TIMER_ACTION_STATUS_UPDATE",
"AE_ON_DEMAND_QUERY_RESULT",
"AE_ON_DEMAND_POSTERS_AVAILABLE",
"AE_ON_DEMAND_DOWNLOAD_STATUS_UPDATE",
"AE_THROUGHPUT_TEST_PREPARE",
"AE_THROUGHPUT_TEST_ABORT",
"AE_STBH_REQUEST_CLIENT_INFO",
"AE_TUNER_USAGE_UPDATE_V2",
"AE_SEND_IRD_COMMAND",
"AE_SYSTEM_RESTARTED",
"AE_EHDD_DEV_STATUS",
"AE_DVR_ARCHIVE_STATUS",
"AE_DVR_DB_CHANGED",
"AE_XIP_DEVICE_DISCOVERED",
"AE_EXTERNAL_KEY_ACTION",
"AE_NOTIFY_TO_POWER_OFF",
"AE_EVTC_AV_STATE_CHANGE",
"AE_EVTC_VIDEO_RESIZE",
"AE_EVTC_AUDIO_LANG_CHANGE",
"AE_EVTC_TRICKMODE",
"AE_EVTC_RR_MEDIA_URL",
"AE_EVTC_RR_WEBGFX_URL",
"AE_CONNECTION_RESET",
"AE_EXTERNAL_RAE_PLAY_XIP",
"AE_EXTERNAL_RAE_TUNE_CH_XIP_V2",
"AE_EXTERNAL_RAE_TRICK_XIP",
"AE_EXTERNAL_RAE_CLIENT_STATUS",
"AE_SEARCH_RESULTS_AVAILABLE",
"AE_CONTROL_WORD_STATUS",
"AE_SMART_CARD_STATUS",
"AE_CHECK_SWITCH_UPDATE",
"AE_PIP_STATUS",
"AE_EXTERNAL_RAE_GET_PLAY_STATUS_XIP",
"AE_STB_PROFILE_CHANGED",
"AE_INVIDI_DATA_UPDATE",
"AE_XIP_DATA_DOWNLOAD_UPDATE",
"AE_EXTERNAL_RAE_GET_PARENTAL_CTRL_SETTING",
"AE_SYSTEM_STANDBY_STATUS",
"AE_RECEIVER_STANDBY_STATUS",
"AE_HAS_PLAYBACK_STATUS",
"AE_DAILY_SCHEDULE_CHANGED",
"AE_SETTINGS_CHANGED_CLOSED_CAPTION_ENABLE",
"AE_SETTINGS_CHANGED_CLOSED_CAPTION",
"AE_SETTINGS_CHANGED_PARENTAL_CONTROL_ENABLE",
"AE_SETTINGS_CHANGED_PARENTAL_CONTROLS",
"AE_EXTERNAL_RAE_REBOOT_STB",
"AE_AUDIO_VIDEO_BLANK_STATUS",
"AE_EPG_EIT_FILE_UPDATED",
"AE_EPG_PF_FILE_UPDATED",
"AE_REMOTE_PAIRED",
"AE_DVR_IPCAM_DB_CHANGED",
"AE_SETTINGS_CHANGED_PARENTAL_CONTROL_PASSWORD",
"AE_SETTINGS_CHANGED_GUIDE",
"AE_SETTINGS_CHANGED_CURSOR_ENABLE",
"AE_SETTINGS_CHANGED_CURSOR",
"AE_SETTINGS_CHANGED_CHANNEL_PREFERENCE",
"AE_SETTINGS_CHANGED_MULTI_CHANNEL_SWAP",
"AE_SETTINGS_CHANGED_MULTI_CHANNEL_RECALL",
"AE_SETTINGS_CHANGED_AUDIO_LANGUAGE_ENABLE",
"AE_SETTINGS_CHANGED_AUDIO_LANGUAGE",
"AE_SETTINGS_CHANGED_AUDIO",
"AE_SETTINGS_CHANGED_TIMER_DEFAULTS",
"AE_SETTINGS_CHANGED_PTAT_ENABLE",
"AE_SETTINGS_CHANGED_VIDEO_FORMAT",
"AE_SETTINGS_CHANGED_REMOTE_CODES",
"AE_SETTINGS_CHANGED_REMOTE",
"AE_SETTINGS_CHANGED_REMOTE_MODE_ENABLE",
"AE_SETTINGS_CHANGED_SYSTEM_NAME",
"AE_SETTINGS_CHANGED_TV",
"AE_SETTINGS_CHANGED_TV_FORMAT",
"AE_SETTINGS_CHANGED_TV_ENHANCEMENTS_ENABLE",
"AE_SETTINGS_CHANGED_HDMI_CEC_ENABLE",
"AE_SETTINGS_CHANGED_NETWORK_BRIDGING_ENABLE",
"AE_SETTINGS_CHANGED_PHONE",
"AE_SETTINGS_CHANGED_CALLER_ID_ENABLE",
"AE_SETTINGS_CHANGED_WHOLE_HOME",
"AE_SETTINGS_CHANGED_WJAP_NAME",
"AE_SETTINGS_CHANGED_CHECK_SWITCH_ALTERNATE_ENABLE",
"AE_SETTINGS_CHANGED_INACTIVITY_STANDBY_ENABLE",
"AE_SETTINGS_CHANGED_INACTIVITY_STANDBY",
"AE_SETTINGS_CHANGED_NIGHTLY_UPDATE_ENABLE",
"AE_SETTINGS_CHANGED_NIGHTLY_UPDATE",
"AE_SETTINGS_CHANGED_CONTROL_4_ENABLE",
"AE_SETTINGS_CHANGED_BLUETOOTH_ENABLE",
"AE_SETTINGS_CHANGED_MEDIA_DEVICE_PAIRING_ENABLE",
"AE_NET_CONNECTION_CHANGED",
"AE_NET_IF_STATISTICS",
"AE_ON_DEMAND_RENTAL_STATUS_CHANGED",
"AE_INSTALL_WIZARD_STEP_STATUS",
"AE_PTAT_RECORDING_STATUS",
"AE_SETTINGS_CHANGED_AUTO_TRANSCODE_ENABLE",
"AE_INTERRUPT_TRIGGER",
"AE_TEXT_TRIGGER",
"AE_SW_UPGRADE",
"AE_CHECK_SWITCH_PROGRESS",
"AE_CHECK_SWITCH_COMPLETE",
"AE_NOTIFY_DISPLAY_TEXT_READY",
"AE_NOTIFY_DATA_SEARCH_STATUS",
"AE_CONNECTION_QUALITY_CHANGED",
"AE_WHOLE_HOME_LINK_STATUS_NOTIFICATION",
"AE_WIFI_CONNECTION_NOTIFICATION",
"AE_RESET_NETWORK_STATUS",
"AE_BRIDGING_STATUS",
"AE_WIFI_CONNECTION_TEST_STATUS",
"AE_SCAN_WIFI_NETWORK_COMPLETE",
"AE_WPS_SETUP_STATUS",
"AE_LINK_TO_HOPPER_COMPLETE",
"AE_JOEY_CONNECTION_STATUS",
"AE_OFFAIR_SIGNAL_STRENGTH",
"AE_OFFAIR_SCAN_PROGRESS",
"AE_OFFAIR_SCAN_COMPLETE",
"AE_NOTIFY_ENTITY_INTENT_READY",
"AE_TUNE_TRIGGER",
"AE_BROWSER_TRIGGER",
"AE_REMOTE_UNPAIRED",
"AE_REMOTE_BATTERY_LEVEL_CHANGED",
"AE_REMOTE_FW_UPDATE_STATUS",
"AE_OD_QUERY_RESULT_AVAILABLE",
"AE_AUTHORIZATION_STATUS",
"AE_CONNECTION_PING",
"AE_EXTERNAL_APP_STATUS",
"AE_BACKUP_DEVICES_STATUS",
"AE_RESTORE_DEVICE_STATUS",
"AE_STB_SETTING_STATUS_FROM_REMOTE",
"AE_STANDARD_TIMER_TRIGGER",
"AE_DISHPASS_TIMER_TRIGGER",
"AE_REMOTE_LEARNING_STATUS",
"AE_BLUETOOTH_HW_STATUS",
"AE_BLUETOOTH_DEV_SCAN_STATUS",
"AE_BLUETOOTH_DEV_STATE_CHANGE",
"AE_SETTINGS_CHANGED_DVR_SORT",
"AE_SETTINGS_CHANGED_MEDIA_GROUP_BY",
"AE_SETTINGS_CHANGED_WIFI",
"AE_SETTINGS_CHANGED_SLING_POPUP",
"AE_WJAP_NAME_CHANGED",
"AE_WJAP_WL_CHANNEL_CHANGED",
"AE_WJAP_REBOOTED",
"AE_WJAP_CONNECTED_DEVICES_CHANGED",
"AE_TV_COMPATIBILITY_CHANGED",
"AE_ELCC_DOWNLOAD_STATUS",
"AE_INTERNET_SPEED_TEST_STATUS",
"AE_DVR_HARD_DRIVE_STATUS",
"AE_EHDD_HW_STATUS",
"AE_HDD_ACTIVITY_STATUS",
"AE_AUTO_ACTIVATION_STATUS",
"AE_REMOTE_TUNER_STATUS",
"AE_DEVICE_PAIRING_STATUS",
"AE_WIRELESS_HW_STATUS",
"AE_UNSUPPORTED_USB_DEVICE",
"AE_ENTER_STANDBY_REQUEST",
"AE_SLINGROSE_HW_STATUS",
"AE_OFFAIR_HW_STATUS",
"AE_ESATA_HW_STATUS",
"AE_IRD_DISPLAY_TEXT",
"AE_RESET_STB_USER_SETTINGS_COMPLETE",
"AE_VERIFY_SWITCH_PROGRESS",
"AE_SIGNAL_CHECK_PROGRESS",
"AE_STBH_CONFIRMATION",
"AE_DISPLAY_REQUEST",
"AE_SETTINGS_CHANGED_HDMI_HDCP_ENABLE",
"AE_EPG_DOWNLOAD_PROGRESS",
"AE_STANDBY_TASK_STATUS_UPDATE",
"AE_PARENTAL_CTRL_SETTINGS_COPY_RESULT",
"AE_SETTINGS_CHANGED_OD_POPUPS_ON_OFF",
"AE_SETTINGS_CHANGED_HELP_OVERLAY_INFO_POPUP_ON_OFF",
"AE_HOPPERGO_STATUS",
"AE_SETTINGS_CHANGED_HOME_MEDIA_SETTINGS",
"AE_CTRLPT_DIRECTORY_LIST_QUERY_STATUS",
"AE_CTRLPT_REFRESH_SERVER_LIST_NOTIFICATION",
"AE_CTRLPT_PLAY_STATUS_CHANGE",
"AE_CTRLPT_SERVER_NOTIFICATION",
"AE_REQUEST_ACCOUNT_ID",
"AE_LCI_STATUS_WITH_DATA",
"AE_LCI_STATUS",
"AE_PRM_STATUS",
"AE_SETTINGS_CHANGED_DVR_SCHEDULE",
"AE_SETTINGS_CHANGED_MOBILE_ANTENNA",
"AE_MOBILE_ANTENNA_DETECTED",
"AE_STREAMING_BUFFER_STATUS",
"AE_DECODER_RELEASED",
"AE_H2H_TRANSFER_STATUS",
"AE_ODU_STATUS",
"AE_SETTINGS_CHANGED_GUIDE_APPEARANCE",
"AE_MULTI_PIP_STATUS",
"AE_MEDIA_RENDERER_PLAY_NOTIFICATION",
"AE_REMOTE_NEW_FW_AVAILABLE",
"AE_SETTINGS_CHANGED_SCREEN_LANGUAGE",
"AE_FORCE_STANDBY",
"AE_REFURBISH_SMART_CARD_STATUS",
"AE_PLAY_EVENT_STATUS",
"AE_SETTINGS_CHANGED_UI_THEME",
"AE_SETTINGS_CHANGED_CVAA",
"AE_SETTINGS_CHANGED_CVAA_SPEECH_ENABLE",
"AE_SETTINGS_CHANGED_CVAA_MAGNIFICATION_ENABLE",
"AE_QAM_HW_STATUS",
"AE_QAM_SCAN_PROGRESS",
"AE_SPEECH_COMPLETE",
"AE_SETTINGS_CHANGED_HOME_SCREEN",
"AE_CUST_MSG_NOTIFICATION",
"AE_SETTINGS_CHANGED_SEARCH_FILTER",
"AE_AV_RESOURCE_STOLEN",
"AE_NOTIFY_VOICE_DATA_READY",
"AE_SETTINGS_CHANGED_CVAA_AUDIO_DESCRIPTION_ENABLE",
"AE_SETTINGS_CHANGED_WHOLE_HOME_MUSIC_ENABLE",
"AE_SETTINGS_CHANGED_TOUCHPAD_SENSITIVITY",
"AE_ALEXA_PAIRING_STATUS",
"AE_EXTERNAL_SW_DOWNLOAD_STATUS",
"AE_FAVORITE_SPORTING_LIST_CHANGED",
"AE_GAME_NOTIFICATION",
"AE_SETTINGS_CHANGED_MDU_TV_ENABLE",
"AE_MAINTENANCE_REQUEST",
"AE_GRASSHOPPER_CONFIG_INFO_CHANGED",
"AE_GRASSHOPPER_AUTH_INFO_CHANGED",
"AE_GOOGLE_ASSISTANT_PAIRING_STATUS",
"AE_WALLET_GET_PAYMENT_INFO_STATUS",
"AE_WALLET_MANAGE_PAYMENT_INFO_STATUS",
"AE_DYNAMIC_PROMOTIONS_UPDATED",
"AE_DISH_IP_STREAM_SOURCE_DETECTED",
"AE_DARTH_TEST_STATUS",
"AE_NOTIFY_VOICE_VOLUME",
"AE_HORNET_SIGNAL_STRENGTH",
"AE_HORNET_STATUS",
"AE_COPROCESSOR_READY",
"AE_INDEPENDA_STATE",
"AE_SETTINGS_CHANGED_CLIENT_AV_SYNC",
"AE_SETTINGS_CHANGED_VOICE_CONTROL_MODE",
"AE_AUTHORIZED_HOST_UPDATE",
"AE_COPROCESSOR_PLUGIN_STATUS",
"AE_COPROCESSOR_WORKING",
"AE_SETTINGS_CHANGED_COPROC_POPUP",
"AE_COPROCESSOR_SUPPORTED",
"AE_SETTINGS_CHANGED_REQUEST_INTERNET",
"AE_BINGE_WATCHING",
"AE_INVALID_FREQ_TABLE",
"AE_OTA_SIGNAL_STRENGTH",
"AE_DVR_EVT_IN_USE",
"AE_HDD_ERR",
"AE_HDD_FULL",
"AE_IPVOD_DOWNLOAD_STATUS",
"AE_IPVOD_PB_BUFFERING",
"AE_SW_DOWNLOAD",
"AE_STB_REBOOT",
"AE_FACTORY_RESET",
"AE_EXT_USB_DEV_STATUS",
"AE_SSR_SCAN_COMPLETE",
"AE_VIP_TIMER_RESTORE_STATUS",
"AE_ID_MAX"
]

##########################################
# main class for interaction with STB.
# the __init__ forms all STB info based on init params, script args, info from base file
# for production STBs also provide attach/detach and pair (if needed)
class STB(object):
   def __str__(self):
      line = ""
      if self.name: line += self.name + " "                          # STBs name
      line += "stb={} ip={}".format(self.stb, self.ip) # STBs Receiver ID, ip, port
      if self.cid: line += " cid={}".format(self.cid)
      line += " ({}:{})".format(self.login, self.passwd) if self.login and self.passwd else " (dev)"
      line += " rid={}".format(self.rid)
      return line

   def vbprint(self, *args, **kwargs):
      if self.verbose: print (*args, **kwargs)

   def __init__(self, args=None, name=None, prod=False):
      self.name = name
      self.stb  = None # the STB's Receiver ID
      self.rid  = None # this PC ReceiverID
      self.ip   = None
      self.port = None
      self.verbose = False
      self.prod   = prod
      self.login  = None
      self.passwd = None
      self.cid    = None

      # set stb info from args (if set by user)
      if args:
         if not self.name and args.name:    self.name    = args.name
         if args.ip:      self.ip      = args.ip
         if args.port:    self.port    = args.port
         if args.stb:     self.stb     = args.stb
         if args.verbose: self.verbose = args.verbose
         if args.prod:    self.prod    = args.prod
         if args.login:   self.login   = args.login
         if args.passwd:  self.passw   = args.passwd

      # load rest of info from file
      base = sgs_load_base()
      if not base:
         self.vbprint("fail read STB base file")
      else:
         if not self.name and "default_stb" in base.keys():  self.name = base["default_stb"]
         if not self.name:
            self.vbprint ("stb name not set")
         else:
            if "stbs" not in base.keys():
               self.vbprint("\"stbs\" not found in STB base file")
            else:
               if self.name not in base["stbs"].keys():
                  self.vbprint ("'{}' not found in STB base file".format(self.name))
               else:
                  # load params for specified stb name
                  stb_info = base["stbs"][self.name]
                  if not self.ip     and "ip"     in stb_info.keys(): self.ip     = stb_info["ip"]
                  if not self.port   and "port"   in stb_info.keys(): self.port   = stb_info["port"]
                  if not self.stb    and "stb"    in stb_info.keys(): self.stb    = stb_info["stb"]
                  if not self.login  and "lname"  in stb_info.keys(): self.login  = stb_info["lname"]
                  if not self.passwd and "passwd" in stb_info.keys(): self.passwd = stb_info["passwd"]
                  if                     "prod"   in stb_info.keys(): self.prod   = stb_info["prod"]
         # read default values if not read yet
         if not self.ip     and "default_stb_ip"     in base.keys(): self.ip     = base["default_stb_ip"]
         if not self.port   and "default_stb_port"   in base.keys(): self.port   = base["default_stb_port"]

      # set default values:
      if not self.port: self.port = DEFAULT_STB_PORT

      # use default receiver ID if not set and not a production STB
      if not (self.login and self.passwd) and not self.stb: self.stb = DEFAULT_RECEIVER

      # check if all required params available
      if not self.ip:
         print ("no STB IP. exit")
         exit()
      if bool(self.login) != bool (self.passwd):
         print ("error login ({}) / passwd ({})".format(self.login, self.passwd))
         exit()


      if not self.stb:
         print ("STBs Reveiver ID not set. Exit...")
         exit()

      # set this device Receiver ID based on Mac
      self.mac = get_local_iface_mac()
      self.rid = sgs_get_receiver_id()

      #  ---- stb info collecting complete

      # print self info
      self.vbprint (self)

      # attach if it is prod stb
      if self.login and self.passwd:
         self.prod = True
      # now pair/attach only if prod
      if self.prod:
         # pair if login/passwd not set
         if not ((bool(self.login) and bool(self.passwd))):
            # pair and save login passwd to file
            if self.pair() and "stbs" in base.keys() and self.name and self.name in base["stbs"].keys():
               base["stbs"][self.name]["passwd"] = self.passwd
               base["stbs"][self.name]["lname"]  = self.login
               sgs_save_base(base=base, filename=BASE_FILE_NAME)
         # attach if cid not set
         if (bool(self.login) and bool(self.passwd)) and (not self.cid):
            self.attach()

   #def __del__(self):
      # TODO needs fix. the python script terminates itself before detach complete
      #if self.cid:
      #   self.detach()

   def query_unsecure(self, data, url=None):
      if not url: url = f"http://{self.ip}:{self.port}/www/sgs"
      self.vbprint ("  --- request:  ",json.dumps(data))
      try:
         response = requests.post(url, data=json.dumps(data))
      except Exception as inst:
         print("URL request failed:", inst)
         return None
      self.vbprint ("  --- response: ", response.text)
      # parse response
      try:
         result = json.loads(response.text)
      except:
         print("error Json parse")
         result = {'result' : -3}
      return result

   def query_noauth(self, data, url=None):
      noauth_url = url or f'http://{self.ip}:{self.port}/sgs_noauth'
      return self.query_unsecure(data, url=noauth_url)

   def query_secure(self, data):
      headers = {'content-type': 'application/json'}
      url = 'https://' + self.ip + '/www/sgs'
      # determine the relative path from this file to the crt & key files
      relative_path = os.path.dirname(os.path.abspath(__file__))
      relative_path += os.path.sep

      if not ((os.path.exists(relative_path + "cert.pem") and (os.path.exists(relative_path + "key.pem")))):
         print("cert.pem or key.pem not found")
         result = {'result' : -3}
         return None

      self.vbprint ("  --- request:  ",json.dumps(data))
      try:
         response = requests.post(url, auth=requests.auth.HTTPDigestAuth(self.login, self.passwd),
                                  data=json.dumps(data),
                                  verify=False,
                                  cert=(relative_path + "cert.pem", relative_path + "key.pem"),
                                  headers=headers)
      except Exception as inst:
         print("URL request failed:", inst)
         return None
      self.vbprint ("  --- response: ", response.text)
      try:
         result = json.loads(response.text)
      except:
         print("error Json parse")
         result = {'result' : -3}
      return result


   def sgs_command(self, data):
      if isinstance(data, (str, list)):
         data = json.loads(data)
      if self.login and self.passwd:
         if "cid" not in data:
               data["cid"] = self.cid
         if "receiver" not in data:
               data["receiver"] = self.rid
         return self.query_secure(data), data.get("receiver")
      else:
         if "cid" not in data:
               data["cid"] = DEFAULT_CID
         if "receiver" not in data:
               data["receiver"] = DEFAULT_RECEIVER
         return self.query_secure(data), data.get("receiver")


   '''
   def sgs_command(self, data):
      if (type(data) in (str,list)):
         data = json.loads(data)
      if self.prod:
         if "cid" not in data.keys(): data["cid"] = self.cid
         if "receiver" not in data.keys(): data["receiver"] = self.rid
         return self.query_secure(data)
      else:
         if "cid" not in data.keys(): data["cid"] = DEFAULT_CID
         if "receiver" not in data.keys(): data["receiver"] = DEFAULT_RECEIVER
         return self.query_unsecure(data)

   '''


   # pair PC to STB using PIN.
   # return true/false if paired or not
   def pair(self):
      self.vbprint("Pair to STB")
      querry = {"command": "device_pairing_start", "receiver": self.rid, "stb": self.stb, "app": "JAMboree", "name": "JAMboree", "type": "python", "id": "S9", "mac":self.mac}
      response = self.query_noauth (querry)
      if response["result"] != 1:
         print ("Error start pairing, result", response["result"])
         return False
      pin = input("Please enter PIN: ")
      querry["command"] = "device_pairing_complete"
      querry["pin"] = pin
      response = self.query_noauth (querry)
      if response["result"] != 1:
         print ("Error complete pairing, result", response["result"])
         return False
      self.login  = response["name"]
      self.passwd = response["passwd"]
      print ("login: ", self.login)
      print ("passwd:", self.passwd)
      return True

   def attach(self):
      # first check if already attached
      if self.cid: return
      # now attach
      response = self.query_secure({"command": "attach", "receiver": self.rid, "stb": self.stb, "tv_id": 0, "attr": 1})
      if response and response["result"] == 1:
         self.cid = response["cid"]
      else:
         if response and "result" in response.keys(): print("Error, attach failed with result", response["result"])
         else: print("attach failed with no response")
         return None

   def detach(self):
      response = self.query_secure({"command": "detach", "receiver": self.rid, "cid": self.cid})
      if not (response and response["result"] == 1):
         print ("Error, detach fail", json.dumps(response))
