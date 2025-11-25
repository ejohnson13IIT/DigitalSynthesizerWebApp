from flask import Flask, request, render_template, jsonify
import threading, time, socket
from gpiozero import PWMLED, MCP3008
from time import sleep
from pythonosc.udp_client import SimpleUDPClient

# Physical knobs left to right: pot1, pot2, pot3, pot4
# Remapped: old pot4 -> new pot1, old pot1 -> new pot2, old pot3 stays, old pot2 -> new pot4
pot1 = MCP3008(3)  # Rightmost knob (was pot4) -> parameter 1
pot2 = MCP3008(0)  # Leftmost knob (was pot1) -> parameter 3
pot3 = MCP3008(2)  # 2nd from right (keep as is) -> parameter 2 (mix)
pot4 = MCP3008(1)  # 2nd from left (was pot2) -> needs fixing
osc_ip = "127.0.0.1"   # change if your OSC target is on another device
osc_port = 28017        # Carlas OSC UDP port (make sure this matches Carla)
client = SimpleUDPClient(osc_ip, osc_port)

lastVal1=0
lastVal2=0
lastVal3=0
lastVal4=0

# Mapping functions
def map_pot_to_octave(pot_value):
    """Map to discrete octave (-2, -1, 0, 1, 2)"""
    discrete = int(pot_value * 5)
    if discrete > 4:
        discrete = 4
    return discrete - 2

def map_pot_to_semitone(pot_value):
    """Map to semitone (-12.00 to 12.00) continuous"""
    return pot_value * 24.0 - 12.0

def map_pot_to_mix(pot_value):
    """Map to mix (0.00 to 1.00) continuous"""
    return pot_value

while True:
	
	if abs(int(pot1.value * 100) - lastVal1) > 2:
		semitone_value = map_pot_to_semitone(pot1.value)
		client.send_message("/Carla/0/set_parameter_value", [1, semitone_value])
	
	if abs(int(pot2.value * 100) - lastVal2) > 2:
		octave_value = map_pot_to_octave(pot2.value)
		client.send_message("/Carla/0/set_parameter_value", [3, octave_value])
	
	if abs(int(pot3.value * 100) - lastVal3) > 2:
		mix_value = map_pot_to_mix(pot3.value)
		client.send_message("/Carla/0/set_parameter_value", [2, mix_value])
	
	if abs(int(pot4.value * 100) - lastVal4) > 2:
		semitone_value = map_pot_to_semitone(pot4.value)
		client.send_message("/Carla/0/set_parameter_value", [0, semitone_value])
	lastVal1 = int(pot1.value * 100)
	lastVal2 = int(pot2.value * 100)
	lastVal3 = int(pot3.value * 100)
	lastVal4 = int(pot4.value * 100)
	sleep(0.5)
