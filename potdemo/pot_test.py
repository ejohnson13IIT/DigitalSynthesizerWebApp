from flask import Flask, request, render_template, jsonify
import threading, time, socket
from gpiozero import PWMLED, MCP3008
from time import sleep
from pythonosc.udp_client import SimpleUDPClient

pot2 = MCP3008(0)
pot4 = MCP3008(1)
pot3 = MCP3008(2)
pot1 = MCP3008(3)
osc_ip = "127.0.0.1"
osc_port = 28017
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
		octave_value = map_pot_to_octave(pot1.value)
		client.send_message("/Carla/0/set_parameter_value", [0, octave_value])
		print(f"Pot1 -> Parameter 0 (octave): {octave_value}")
	
	if abs(int(pot2.value * 100) - lastVal2) > 2:
		semitone_value = map_pot_to_semitone(pot2.value)
		client.send_message("/Carla/0/set_parameter_value", [1, semitone_value])
		print(f"Pot2 -> Parameter 1 (semitone): {semitone_value:.2f}")
	
	if abs(int(pot3.value * 100) - lastVal3) > 2:
		mix_value = map_pot_to_mix(pot3.value)
		client.send_message("/Carla/0/set_parameter_value", [2, mix_value])
		print(f"Pot3 -> Parameter 2 (mix): {mix_value:.2f}")
	
	if abs(int(pot4.value * 100) - lastVal4) > 2:
		octave_value = map_pot_to_octave(pot4.value)
		client.send_message("/Carla/0/set_parameter_value", [3, octave_value])
		print(f"Pot4 -> Parameter 3 (octave): {octave_value}")
	
	lastVal1 = int(pot1.value * 100)
	lastVal2 = int(pot2.value * 100)
	lastVal3 = int(pot3.value * 100)
	lastVal4 = int(pot4.value * 100)
	sleep(0.5)
