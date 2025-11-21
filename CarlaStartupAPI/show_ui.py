#!/usr/bin/env python3
"""Simple script to show plugin UI from terminal"""
import sys
import os
import time

# Add project root to path for config loader
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config_loader import get_carla_config

# Load configuration
carla_cfg = get_carla_config()

# Add Carla Python backend to path
sys.path.append(carla_cfg.get("python_path", "/usr/share/carla"))

try:
    import carla_backend
except ImportError as exc:
    print(f"Failed to import carla_backend: {exc}")
    sys.exit(1)

# Get library path from config
LIB_PATH = carla_cfg.get("library_path", "/usr/lib/carla/libcarla_standalone2.so")

# Connect to existing Carla instance
print("Connecting to Carla instance...")
host = carla_backend.CarlaHostDLL(LIB_PATH, True)

# Get plugin ID from command line argument, default to 0
plugin_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0

# Check if plugin exists
plugin_count = host.get_current_plugin_count()
if plugin_id >= plugin_count:
    print(f"Error: Plugin {plugin_id} does not exist. Available plugins: 0-{plugin_count-1}")
    sys.exit(1)

plugin_info = host.get_plugin_info(plugin_id)
plugin_name = plugin_info.get("name", f"plugin_{plugin_id}")

print(f"Showing UI for plugin {plugin_id}: {plugin_name}")

# Show the UI
host.show_custom_ui(plugin_id, True)

print("Plugin UI shown. Press Ctrl+C to close.")

# Keep it alive
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nClosing plugin UI...")
    host.show_custom_ui(plugin_id, False)
    print("Done.")

