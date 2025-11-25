from flask import Flask, request, render_template, jsonify
import threading, time, socket
from gpiozero import PWMLED, MCP3008
from time import sleep
from pythonosc.udp_client import SimpleUDPClient

# Initialize pots
pot1 = MCP3008(0)  # Octave (-2 to 2, discrete)
pot2 = MCP3008(1)  # Semitone (-12 to 12, continuous)
pot3 = MCP3008(2)  # Mix (0 to 1, continuous)
pot4 = MCP3008(3)  # Voice selector (0, 1, 2, 3)

osc_ip = "127.0.0.1"
osc_port = 28017
client = SimpleUDPClient(osc_ip, osc_port)

# Last raw ADC values for change detection
last_raw1 = 0
last_raw2 = 0
last_raw3 = 0
last_raw4 = 0

# Mapping functions
def map_pot_to_voice_selector(pot_value):
    """Map pot4 (0-1) to voice selector (0, 1, 2, 3)"""
    return int(pot_value * 4) % 4

def map_pot_to_octave(pot_value):
    """Map pot1 (0-1) to octave (-2, -1, 0, 1, 2) discrete"""
    # Map 0-1 to 0-4, then shift to -2 to 2
    discrete = int(pot_value * 5)
    if discrete > 4:
        discrete = 4
    return discrete - 2

def map_pot_to_semitone(pot_value):
    """Map pot2 (0-1) to semitone (-12.0 to 12.0) continuous"""
    return pot_value * 24.0 - 12.0

def map_pot_to_mix(pot_value):
    """Map pot3 (0-1) to mix (0.0 to 1.0) continuous"""
    return pot_value

def get_parameter_indices(voice):
    """Get the base parameter indices for the selected voice"""
    # voice 0 -> parameters 0, 1, 2
    # voice 1 -> parameters 3, 4, 5
    # voice 2 -> parameters 6, 7, 8
    # voice 3 -> parameters 9, 10, 11
    base = voice * 3
    return base, base + 1, base + 2  # octave, semitone, mix

# Main loop
while True:
    # Read pot values
    raw1 = int(pot1.value * 1000)
    raw2 = int(pot2.value * 1000)
    raw3 = int(pot3.value * 1000)
    raw4 = int(pot4.value * 1000)
    
    # Get current voice selection from pot4
    current_voice = map_pot_to_voice_selector(pot4.value)
    param_octave, param_semitone, param_mix = get_parameter_indices(current_voice)
    
    # Check for knob changes and send OSC messages
    if abs(raw1 - last_raw1) > 2:
        octave_value = map_pot_to_octave(pot1.value)
        client.send_message("/Carla/0/set_parameter_value", [param_octave, octave_value])
        last_raw1 = raw1
    
    # Pot 2 = semitone
    if abs(raw2 - last_raw2) > 2:
        semitone_value = map_pot_to_semitone(pot2.value)
        client.send_message("/Carla/0/set_parameter_value", [param_semitone, semitone_value])
        last_raw2 = raw2
    
    # Pot 3 = mix
    if abs(raw3 - last_raw3) > 2:
        mix_value = map_pot_to_mix(pot3.value)
        client.send_message("/Carla/0/set_parameter_value", [param_mix, mix_value])
        last_raw3 = raw3
    
    # Pot 4 = voice selector (also sends to parameter index 12)
    if abs(raw4 - last_raw4) > 2:
        # Send discrete voice selector value (0, 1, 2, 3) to parameter index 12
        pot4_value = map_pot_to_voice_selector(pot4.value)
        client.send_message("/Carla/0/set_parameter_value", [12, pot4_value])
        last_raw4 = raw4
    
    sleep(0.05)  # Faster polling for smoother response
