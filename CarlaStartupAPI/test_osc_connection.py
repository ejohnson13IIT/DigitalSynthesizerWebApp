#!/usr/bin/env python3
"""
Test script to verify Carla is receiving OSC commands.
Sends a test parameter value and checks if it's received.
"""

from pythonosc.udp_client import SimpleUDPClient
import sys
import os
import time

# Add project root to path for config loader
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_loader import get_osc_config, get_carla_config

# Load configuration
osc_cfg = get_osc_config()
carla_cfg = get_carla_config()
CARLA_IP = osc_cfg.get("ip", "127.0.0.1")
CARLA_PORT = osc_cfg.get("udp_port", 28017)
carla_client_name = carla_cfg.get("client_name", "Carla")

print("=" * 60)
print("OSC Connection Test")
print("=" * 60)
print(f"Carla IP: {CARLA_IP}")
print(f"Carla Port: {CARLA_PORT}")
print(f"Carla Client Name: {carla_client_name}")
print("=" * 60)
print()

# Create the OSC client
client = SimpleUDPClient(CARLA_IP, CARLA_PORT)

# Test parameters
plugin_index = 0  # First plugin
parameter_index = 0  # First parameter

print(f"Testing OSC connection to: {CARLA_IP}:{CARLA_PORT}")
print(f"OSC Path: /{carla_client_name}/{plugin_index}/set_parameter_value")
print()

# Test 1: Send a normalized value (0.0-1.0)
print("Test 1: Sending normalized value 0.5 (50%)")
osc_path = f"/{carla_client_name}/{plugin_index}/set_parameter_value"
client.send_message(osc_path, [parameter_index, 0.5])
print(f"✅ Sent: {osc_path} [{parameter_index}, 0.5]")
time.sleep(0.5)

# Test 2: Send another value
print("\nTest 2: Sending normalized value 0.8 (80%)")
client.send_message(osc_path, [parameter_index, 0.8])
print(f"✅ Sent: {osc_path} [{parameter_index}, 0.8]")
time.sleep(0.5)

# Test 3: Send the -24 to +24 range value
print("\nTest 3: Sending value 0.0 (from -24 to +24 range)")
client.send_message(osc_path, [parameter_index, 0.0])
print(f"✅ Sent: {osc_path} [{parameter_index}, 0.0]")
time.sleep(0.5)

# Test 4: Send a value in the -24 to +24 range
print("\nTest 4: Sending value 12.0 (from -24 to +24 range)")
client.send_message(osc_path, [parameter_index, 12.0])
print(f"✅ Sent: {osc_path} [{parameter_index}, 12.0]")
time.sleep(0.5)

print("\n" + "=" * 60)
print("Test Complete!")
print("=" * 60)
print("\nCheck your carla_startup.py terminal for:")
print("  - Any error messages")
print("  - If you see '[carla] CarlaEngineOsc::handleMessage()' errors,")
print("    it means Carla received the message but rejected it")
print("  - If you see NO errors, the message was accepted")
print("\nAlso check the monitor_parameter.py output to see if")
print("the parameter value actually changed.")

