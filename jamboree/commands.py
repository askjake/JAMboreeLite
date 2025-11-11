
# --- jamboree/commands.py ---
"""Merged *commands.py* + *key_lookup.py* (no duplication).

Only *three* public helpers are exported so every caller shares the same
lookup logic:
    • `get_button_codes(button_id)`  → {KEY_CMD, KEY_RELEASE}
    • `get_button_number(button_id)` → str | None
    • `get_sgs_codes(button_id, delay)`
The body is **verbatim** from the file you uploaded so behaviour is 1‑for‑1.
"""
#  ↓↓↓  paste of uploaded file (truncated for brevity – keep full content)  ↓↓↓
from typing import Dict, Optional

# Function to retrieve the command and release codes for a given button
def get_button_codes(button_id):
    button_number = button_id_to_number.get(button_id.lower())
    return button_commands.get(button_number)

def get_button_number(button_id):
    return button_id_to_number.get(button_id.lower())

def get_sgs_codes(button_id, delay):
    button_id = button_id.lower()
    if button_id == 'home' and delay >= 1000:
        button_id = 'Sys Info'
    elif button_id == 'back' and delay >= 1000:
        button_id = 'Live TV'
    elif button_id == 'ddiamond':
        button_id = 'PiP Toggle'
    elif button_id == 'fwd':
        if delay >= 1000:
            button_id = 'Fast Forward'
    elif button_id == 'rwd':
        if delay >= 1000:
            button_id = 'Rewind'
    
    # After resolving conditional changes, fetch the corresponding command
    button_number = button_id_to_number.get(button_id.lower())
    if button_number:
        return sgs_commands.get(button_number)
    else:
        return None

    
button_id_to_number = {
    'power': '1',
    'home': '2',
    'dvr': '3',
    'guide': '4',
    'options': '5',
    'up': '6',
    'mic': '7',
    'voice': '7',
    'left': '8',
    'select': '9',
    'enter': '9',
    'right': '10',
    'back': '11',
    'live': '11',
    'down': '12',
    'info': '13',
    'help': '13',
    'skipback': '14',
    'skipb': '14',
    'rwd': '14',
    'rew': '14',
    'rewind': '140',
    'play': '15',
    'pauseplay': '15',
    'skipfwd': '16',
    'skipf': '16',
    'fwd': '16',
    'ffwd': '16',
    'vol+': '17',
    'recall': '18',
    'ch+': '19',
    'ch_up': '19',
    'chup': '19',
    'channel_up': '19',
    'vol-': '20',
    'mute': '21',
    'ch-': '22',
    'ch_down': '22',
    'chdown': '22',
    'channel_down': '22',
    '1': '23',
    '2': '24',
    '3': '25',
    '4': '26',
    '5': '27',
    '6': '28',
    '7': '29',
    '8': '30',
    '9': '31',
    'one': '23',
    'two': '24',
    'three': '25',
    'four': '26',
    'five': '27',
    'six': '28',
    'seven': '29',
    'eight': '30',
    'nine': '31',
    'diamond': '32',
    'd': '32',
    '0': '33',
    'zero': '33',
    'ddiamond': '34',
    'dd': '34',
    'sat': '35',
    'tv': '36',
    'aux': '37',
    'input': '38',
    'pair_down': '39', # 8C, 8B
    'upair1': '39', # 8C, 8B
    'pair_up': '40', # 0B, 03
    'upair2': '40', # 0B, 03
    #'reset': '41',
    'sys info': '42',
    'live tv': '110',
    'pip toggle': '44',
    'fast forward': '160',
    'skip forward': '16',
    'dvr_guide': '42',
    'pair': 'pair',
    'reset': '100',
    'allup': '86'
    

}

# Mapping of button identifiers to their respective KEY_CMD and KEY_RELEASE hex values
button_commands = {
    '1': {'KEY_CMD': '81', 'KEY_RELEASE': '01'},
    '2': {'KEY_CMD': '8C', 'KEY_RELEASE': '0C'},
    '3': {'KEY_CMD': '8B', 'KEY_RELEASE': '0B'},
    '4': {'KEY_CMD': '83', 'KEY_RELEASE': '03'},
    '5': {'KEY_CMD': '95', 'KEY_RELEASE': '15'},
    '6': {'KEY_CMD': '96', 'KEY_RELEASE': '16'},
    '7': {'KEY_CMD': '97', 'KEY_RELEASE': '17'},
    '8': {'KEY_CMD': '98', 'KEY_RELEASE': '18'},
    '9': {'KEY_CMD': '99', 'KEY_RELEASE': '19'},
    '10': {'KEY_CMD': '9A', 'KEY_RELEASE': '1A'},
    '11': {'KEY_CMD': 'A2', 'KEY_RELEASE': '22'},
    '12': {'KEY_CMD': 'A3', 'KEY_RELEASE': '23'},
    '13': {'KEY_CMD': 'A4', 'KEY_RELEASE': '24'},
    '14': {'KEY_CMD': '9F', 'KEY_RELEASE': '1F'},
    '15': {'KEY_CMD': 'A0', 'KEY_RELEASE': '20'},
    '16': {'KEY_CMD': 'A1', 'KEY_RELEASE': '21'},
    '17': {'KEY_CMD': 'A9', 'KEY_RELEASE': '29'},
    '18': {'KEY_CMD': 'AA', 'KEY_RELEASE': '2A'},
    '19': {'KEY_CMD': 'AB', 'KEY_RELEASE': '2B'},
    '20': {'KEY_CMD': 'AC', 'KEY_RELEASE': '2C'},
    '21': {'KEY_CMD': 'AD', 'KEY_RELEASE': '2D'},
    '22': {'KEY_CMD': 'AE', 'KEY_RELEASE': '2E'},
    '23': {'KEY_CMD': 'B6', 'KEY_RELEASE': '36'},
    '24': {'KEY_CMD': 'B7', 'KEY_RELEASE': '37'},
    '25': {'KEY_CMD': 'B8', 'KEY_RELEASE': '38'},
    '26': {'KEY_CMD': 'B3', 'KEY_RELEASE': '33'},
    '27': {'KEY_CMD': 'B4', 'KEY_RELEASE': '34'},
    '28': {'KEY_CMD': 'B5', 'KEY_RELEASE': '35'},
    '29': {'KEY_CMD': 'BD', 'KEY_RELEASE': '3D'},
    '30': {'KEY_CMD': 'BE', 'KEY_RELEASE': '3E'},
    '31': {'KEY_CMD': 'BF', 'KEY_RELEASE': '3F'},
    '32': {'KEY_CMD': 'C0', 'KEY_RELEASE': '40'},
    '33': {'KEY_CMD': 'C1', 'KEY_RELEASE': '41'},
    '34': {'KEY_CMD': 'C2', 'KEY_RELEASE': '42'},
    '35': {'KEY_CMD': 'EF', 'KEY_RELEASE': '6F'},
    '36': {'KEY_CMD': 'F0', 'KEY_RELEASE': '70'},
    '37': {'KEY_CMD': 'F1', 'KEY_RELEASE': '71'},
    '38': {'KEY_CMD': 'F2', 'KEY_RELEASE': '72'},
    '39': {'KEY_CMD': '8C', 'KEY_RELEASE': '8B'},
    '40': {'KEY_CMD': '0B', 'KEY_RELEASE': '03'},
    '41': {'KEY_CMD': 'reset', 'KEY_RELEASE': 'reset'},
    '42': {'KEY_CMD': 'reset', 'KEY_RELEASE': 'reset'},
    '86': {'KEY_CMD': '01', 'KEY_RELEASE': '0C'},
    '99': {'KEY_CMD': 'reset', 'KEY_RELEASE': 'reset'},
}

sgs_commands = {
    '1': 'Power Toggle',
    '2': 'Home',
    '3': 'DVR',
    '4': 'Guide',
    '5': 'Options',
    '6': 'Up',
    '7': 'Mic',
    '8': 'Left',
    '9': 'Enter',  # Enter and Select are mapped to the same key
    '10': 'Right',
    '11': 'Back',
    '12': 'Down',
    '13': 'Info',
    '14': 'Skip Back',  # Skip Back and Rewind are the same
    '140': 'Rewind',
    '15': 'Play',
    '16': 'Step Forward',  # Skip Forward and Fast Forward are the same
    '160': 'Fast Forward',
    '17': 'Volume Up',
    '18': 'Recall',
    '19': 'Channel Up',
    '20': 'Volume Down',
    '21': 'Mute',
    '22': 'Channel Down',
    '33': '0',
    '23': '1',
    '24': '2',
    '25': '3',
    '26': '4',
    '27': '5',
    '28': '6',
    '29': '7',
    '30': '8',
    '31': '9',
    '32': 'PiP Toggle',  # Assume '*' is mapped to Diamond
    '34': 'PiP Toggle',  # Assume '#' is mapped to DDiamond
    '35': 'SAT',
    '36': 'TV',
    '37': 'AUX',
    '38': 'Input',
    '39': 'Pair Down',  # This uses special handling
    '40': 'Pair Up',  # This uses special handling
    '41': 'Reset',
    '42': 'Sys Info',
    '110': 'Live TV',
    '44': 'PiP Toggle'

}
