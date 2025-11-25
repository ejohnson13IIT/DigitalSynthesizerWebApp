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

# Soft catch state
NUM_SELECTORS = 4
stored_octave = [0] * NUM_SELECTORS
stored_semitone = [0.0] * NUM_SELECTORS
stored_mix = [0.5] * NUM_SELECTORS

current_selector = 0
previous_selector = -1

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
    "octave": None,
    "semitone": None,
    "mix": None
}

THRESHOLD_OCTAVE = 0.1
THRESHOLD_SEMITONE = 0.48
THRESHOLD_MIX = 0.02

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

def map_pot_to_selector(pot_value):
	"""Map to selector (0, 1, 2, 3)"""
	discrete = int(pot_value * 4)
	if discrete > 3:
		discrete = 3
	return discrete

def normalize_octave(octave_value):
    """Normalize octave (-2 to 2) to (0.0 to 1.0) for OSC"""
    return (octave_value + 2) / 4.0

def normalize_semitone(semitone_value):
    """Normalize semitone (-12.0 to 12.0) to (0.0 to 1.0) for OSC"""
    return (semitone_value + 12.0) / 24.0

def normalize_selector(selector_value):
    """Normalize selector (0 to 3) to (0.0 to 1.0) for OSC"""
    return selector_value / 3.0

def get_parameter_indices(selector):
    """Get parameter indices based on selector value"""
    base = selector * 3
    return base, base + 1, base + 2

def on_selector_change(new_selector):
    """Called when selector changes - reset capture state"""
    global current_selector
    current_selector = new_selector
    
    captured["octave"] = False
    captured["semitone"] = False
    captured["mix"] = False
    
    target["octave"] = stored_octave[new_selector]
    target["semitone"] = stored_semitone[new_selector]
    target["mix"] = stored_mix[new_selector]
    
    pot1_inv = 1.0 - pot1.value
    pot2_inv = 1.0 - pot2.value
    pot3_inv = 1.0 - pot3.value
    
    current_octave = map_pot_to_octave(pot1_inv)
    current_semitone = map_pot_to_semitone(pot2_inv)
    current_mix = map_pot_to_mix(pot3_inv)
    
    initial_side["octave"] = "below" if current_octave < target["octave"] else "above"
    initial_side["semitone"] = "below" if current_semitone < target["semitone"] else "above"
    initial_side["mix"] = "below" if current_mix < target["mix"] else "above"

def handle_knob_change(param_name, pot_inverted, threshold, map_func, normalize_func, param_index):
    """Handle knob movement with soft catch algorithm"""
    current = map_func(pot_inverted)
    t = target[param_name]
    
    if not captured[param_name]:
        side = initial_side[param_name]
        
        if side == "below" and current >= t - threshold:
            captured[param_name] = True
        elif side == "above" and current <= t + threshold:
            captured[param_name] = True
        
        if not captured[param_name]:
            return False
    
    if param_name == "octave":
        stored_octave[current_selector] = current
        value_to_send = normalize_func(current)
    elif param_name == "semitone":
        stored_semitone[current_selector] = current
        value_to_send = normalize_func(current)
    elif param_name == "mix":
        stored_mix[current_selector] = current
        value_to_send = current
    
    client.send_message("/Carla/0/set_parameter_value", [param_index, value_to_send])
    return True

while True:
	pot4_inverted = 1.0 - pot4.value
	current_selector = map_pot_to_selector(pot4_inverted)
	
	if current_selector != previous_selector:
		on_selector_change(current_selector)
		previous_selector = current_selector
	
	param_base, param_semitone, param_mix = get_parameter_indices(current_selector)
	
	if abs(int(pot1.value * 100) - lastVal1) > 2:
		pot1_inverted = 1.0 - pot1.value
		octave_value = map_pot_to_octave(pot1_inverted)
		sent = handle_knob_change("octave", pot1_inverted, THRESHOLD_OCTAVE, map_pot_to_octave, normalize_octave, param_base)
		octave_normalized = normalize_octave(octave_value)
		captured_str = "captured" if captured["octave"] else "waiting"
		print(f"Pot1 -> Parameter {param_base} (octave): {octave_value} (normalized: {octave_normalized:.3f}) [Selector: {current_selector}] [{captured_str}]")
	
	if abs(int(pot2.value * 100) - lastVal2) > 2:
		pot2_inverted = 1.0 - pot2.value
		semitone_value = map_pot_to_semitone(pot2_inverted)
		sent = handle_knob_change("semitone", pot2_inverted, THRESHOLD_SEMITONE, map_pot_to_semitone, normalize_semitone, param_semitone)
		semitone_normalized = normalize_semitone(semitone_value)
		captured_str = "captured" if captured["semitone"] else "waiting"
		print(f"Pot2 -> Parameter {param_semitone} (semitone): {semitone_value:.2f} (normalized: {semitone_normalized:.3f}) [Selector: {current_selector}] [{captured_str}]")
	
	if abs(int(pot3.value * 100) - lastVal3) > 2:
		pot3_inverted = 1.0 - pot3.value
		mix_value = map_pot_to_mix(pot3_inverted)
		sent = handle_knob_change("mix", pot3_inverted, THRESHOLD_MIX, map_pot_to_mix, lambda x: x, param_mix)
		captured_str = "captured" if captured["mix"] else "waiting"
		print(f"Pot3 -> Parameter {param_mix} (mix): {mix_value:.2f} [Selector: {current_selector}] [{captured_str}]")
	
	if abs(int(pot4.value * 100) - lastVal4) > 2:
		selector_normalized = normalize_selector(current_selector)
		client.send_message("/Carla/0/set_parameter_value", [12, selector_normalized])
		print(f"Pot4 -> Selector: {current_selector} (normalized: {selector_normalized:.3f}) -> Parameters {param_base}, {param_semitone}, {param_mix}, Parameter 12: {selector_normalized:.3f}")
	
	lastVal1 = int(pot1.value * 100)
	lastVal2 = int(pot2.value * 100)
	lastVal3 = int(pot3.value * 100)
	lastVal4 = int(pot4.value * 100)
	sleep(0.5)
