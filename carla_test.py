from pythonosc.udp_client import SimpleUDPClient
import sys
import os

# Add project root to path for config loader
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_loader import get_osc_config

# Load OSC configuration
osc_cfg = get_osc_config()
CARLA_IP = osc_cfg.get("ip", "127.0.0.1")
CARLA_PORT = osc_cfg.get("udp_port", 28017)

# Create the OSC client
client = SimpleUDPClient(CARLA_IP, CARLA_PORT)

# Plugin index (rack slot)
plugin_index = 0

# Parameter index (within the plugin)
parameter_index = 0

# Value to set (typically between 0.0 and 1.0)
value = 0.8

# Build and send the OSC message
osc_path = f"/Carla/{plugin_index}/set_parameter_value"
client.send_message(osc_path, [parameter_index, value])

print(f"✅ Sent OSC → {osc_path} [{parameter_index}, {value}] to {CARLA_IP}:{CARLA_PORT}")