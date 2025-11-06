import sys, threading, time
sys.path.append("/usr/share/carla")
from carla_backend import CarlaHostDLL

print("Starting Carla Host...")
host = CarlaHostDLL("/usr/lib/carla/libcarla_standalone2.so", True)

# Start engine using JACK (PipeWire provides it!)
ok = host.engine_init("JACK", "WebAppHost")
print("Engine started:", ok)

# Load your project
ok = host.load_project("defaultProj.carxp")
print("Project loaded:", ok)
print("Plugins:", host.get_current_plugin_count())

# Keep engine alive
def idle_loop():
    while True:
        host.engine_idle()
        time.sleep(0.05)

threading.Thread(target=idle_loop, daemon=True).start()

# Prevent script from exiting
input("Press Enter to quit...\n")
