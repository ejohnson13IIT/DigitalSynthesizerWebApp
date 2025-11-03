from pythonosc.udp_client import SimpleUDPClient

# 💡 Replace this with the "Host URL" port Carla shows
# e.g. osc.udp://127.0.0.1:34983/ → use 34983
CARLA_IP = "127.0.0.1"
CARLA_PORT = 28017  # <-- change this to match your actual Host URL port

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