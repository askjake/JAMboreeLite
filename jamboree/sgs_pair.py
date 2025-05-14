#!/usr/bin/env python3
#
# Pair PC to STB
#
# Usage
#  ./sgs_pair.py [-i STB_IP] stb
#   where 
#      - receiver_id - id of receiver to get AE from
#      - ip - is STB IP
#
# Example
#   ./sgs_ae.py R1911705054-56
#   ./sgs_ae.py -i 192.168.1.24 R1911705054-56
#
# Note, pairing code is available in logs:
#   # tail -F  /mnt/MISC_HD/esosal_log/stbCtrl/stbCtrl.0 |grep -e "Pairing code is"

from sgs_lib import *
import argparse

# get params
parser = sgs_arg_parse(description="Pair this PC with STB using pin code")
args = parser.parse_args()

# treat this STB as production so let STB class initializer take care of pairing
stb = STB(args=args, prod=True)

# that's all, nothing more
