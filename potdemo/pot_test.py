from flask import Flask, request, render_template, jsonify
import threading, time, socket
from gpiozero import PWMLED, MCP3008
from time import sleep
from pythonosc.udp_client import SimpleUDPClient

# Initialize pots
pot1 = MCP3008(0)  # Will map to voice selector (0, 1, 2, 3)
pot2 = MCP3008(1)  # Will map to mix (0 to 1, continuous)
pot3 = MCP3008(2)  # Will map to semitone (-12 to 12, continuous)
pot4 = MCP3008(3)  # Will map to octave (-2 to 2, discrete)

osc_ip = "127.0.0.1"
osc_port = 28017
client = SimpleUDPClient(osc_ip, osc_port)

# Voice system: 4 voices (saw=0, square=1, sine=2, triangle=3)
# Each voice has 3 parameters: mix, octave, semitone
NUM_VOICES = 4
mix = [0.5] * NUM_VOICES      # 0.0 to 1.0
octave = [0] * NUM_VOICES     # -2 to 2 (discrete)
semitone = [0.0] * NUM_VOICES # -12.0 to 12.0

# Current voice selector
current_voice = 0

# Soft catch state for each knob
# Pot 4 = octave, Pot 3 = semitone, Pot 2 = mix
captured = {
    "octave": False,
    "semitone": False,
    "mix": False
}

target = {
    "octave": 0,
    "semitone": 0.0,
    "mix": 0.5
}

initial_side = {
    "octave": None,  # "below" or "above"
    "semitone": None,
    "mix": None
}

# Threshold for soft catch (2% of full scale)
THRESHOLD_OCTAVE = 0.1   # For -2 to 2 range
THRESHOLD_SEMITONE = 0.48  # 2% of 24 (full range)
THRESHOLD_MIX = 0.02     # 2% of 1.0

# Last raw ADC values for change detection
last_raw1 = 0
last_raw2 = 0
last_raw3 = 0
last_raw4 = 0

# Mapping functions
def map_pot_to_voice_selector(pot_value):
    """Map pot1 (0-1) to voice selector (0, 1, 2, 3)"""
    return int(pot_value * 4) % 4

def map_pot_to_octave(pot_value):
    """Map pot4 (0-1) to octave (-2, -1, 0, 1, 2) discrete"""
    # Map 0-1 to 0-4, then shift to -2 to 2
    discrete = int(pot_value * 5)
    if discrete > 4:
        discrete = 4
    return discrete - 2

def map_pot_to_semitone(pot_value):
    """Map pot3 (0-1) to semitone (-12.0 to 12.0) continuous"""
    return pot_value * 24.0 - 12.0

def map_pot_to_mix(pot_value):
    """Map pot2 (0-1) to mix (0.0 to 1.0) continuous"""
    return pot_value

def on_voice_change(new_voice):
    """Called when voice selector changes - reset capture state"""
    global current_voice
    current_voice = new_voice
    
    # Reset capture state for all knobs
    captured["octave"] = False
    captured["semitone"] = False
    captured["mix"] = False
    
    # Set target values from stored voice parameters
    target["octave"] = octave[new_voice]
    target["semitone"] = semitone[new_voice]
    target["mix"] = mix[new_voice]
    
    # Read current knob positions and determine initial side
    pot2_val = pot2.value
    pot3_val = pot3.value
    pot4_val = pot4.value
    
    current_octave = map_pot_to_octave(pot4_val)
    current_semitone = map_pot_to_semitone(pot3_val)
    current_mix = map_pot_to_mix(pot2_val)
    
    initial_side["octave"] = "below" if current_octave < target["octave"] else "above"
    initial_side["semitone"] = "below" if current_semitone < target["semitone"] else "above"
    initial_side["mix"] = "below" if current_mix < target["mix"] else "above"

def handle_knob_change(param_name, pot_value, threshold, map_func):
    """Handle knob movement with soft catch algorithm"""
    current = map_func(pot_value)
    t = target[param_name]
    
    if not captured[param_name]:
        # Soft catch: wait until knob passes through target value
        side = initial_side[param_name]
        
        if side == "below" and current >= t - threshold:
            captured[param_name] = True
        elif side == "above" and current <= t + threshold:
            captured[param_name] = True
        
        if not captured[param_name]:
            return  # Ignore knob until it catches up
    
    # Knob is captured - update parameter
    if param_name == "octave":
        octave[current_voice] = int(round(current))
        # Clamp to valid range
        if octave[current_voice] < -2:
            octave[current_voice] = -2
        elif octave[current_voice] > 2:
            octave[current_voice] = 2
        value_to_send = octave[current_voice]
    elif param_name == "semitone":
        semitone[current_voice] = current
        # Clamp to valid range
        if semitone[current_voice] < -12.0:
            semitone[current_voice] = -12.0
        elif semitone[current_voice] > 12.0:
            semitone[current_voice] = 12.0
        value_to_send = semitone[current_voice]
    elif param_name == "mix":
        mix[current_voice] = current
        # Clamp to valid range
        if mix[current_voice] < 0.0:
            mix[current_voice] = 0.0
        elif mix[current_voice] > 1.0:
            mix[current_voice] = 1.0
        value_to_send = mix[current_voice]
    
    # Send OSC message
    # Assuming parameter indices: mix=0, octave=1, semitone=2 per voice
    # Adjust these indices based on your actual OSC parameter mapping
    param_index = current_voice * 3  # Base index for this voice
    if param_name == "mix":
        client.send_message("/WebAppHost/0/set_parameter_value", [param_index, value_to_send])
    elif param_name == "octave":
        client.send_message("/WebAppHost/0/set_parameter_value", [param_index + 1, value_to_send])
    elif param_name == "semitone":
        client.send_message("/WebAppHost/0/set_parameter_value", [param_index + 2, value_to_send])

# Main loop
while True:
    # Read pot values
    raw1 = int(pot1.value * 1000)  # Higher resolution for change detection
    raw2 = int(pot2.value * 1000)
    raw3 = int(pot3.value * 1000)
    raw4 = int(pot4.value * 1000)
    
    # Check for voice selector change (pot1)
    if abs(raw1 - last_raw1) > 2:
        new_voice = map_pot_to_voice_selector(pot1.value)
        if new_voice != current_voice:
            on_voice_change(new_voice)
        last_raw1 = raw1
    
    # Check for knob changes (with soft catch)
    # Pot 2 = mix, Pot 3 = semitone, Pot 4 = octave
    if abs(raw2 - last_raw2) > 2:
        handle_knob_change("mix", pot2.value, THRESHOLD_MIX, map_pot_to_mix)
        last_raw2 = raw2
    
    if abs(raw3 - last_raw3) > 2:
        handle_knob_change("semitone", pot3.value, THRESHOLD_SEMITONE, map_pot_to_semitone)
        last_raw3 = raw3
    
    if abs(raw4 - last_raw4) > 2:
        handle_knob_change("octave", pot4.value, THRESHOLD_OCTAVE, map_pot_to_octave)
        last_raw4 = raw4
    
    sleep(0.05)  # Faster polling for smoother response
