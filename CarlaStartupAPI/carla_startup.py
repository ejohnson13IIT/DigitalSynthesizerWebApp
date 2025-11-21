import sys
import os
import json
import threading
import time
import subprocess
from typing import Any, Dict, List
from flask import Flask, jsonify, request

# Add project root to path for config loader
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from config_loader import (
    get_carla_config,
    get_osc_config,
    get_carla_api_config,
    get_plugin_database_config,
)

# Load configuration
carla_cfg = get_carla_config()
osc_cfg = get_osc_config()
api_cfg = get_carla_api_config()
plugin_db_cfg = get_plugin_database_config()

# Add Carla Python backend to path
sys.path.append(carla_cfg.get("python_path", "/usr/share/carla"))

try:
    import carla_backend  # type: ignore
    import carla_utils  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"Failed to import carla_backend or carla_utils: {exc}")
    raise

# Import ENGINE_OPTION constants for better code clarity
ENGINE_OPTION_OSC_ENABLED = getattr(carla_backend, "ENGINE_OPTION_OSC_ENABLED", 0)
ENGINE_OPTION_OSC_PORT_TCP = getattr(carla_backend, "ENGINE_OPTION_OSC_PORT_TCP", 0)
ENGINE_OPTION_OSC_PORT_UDP = getattr(carla_backend, "ENGINE_OPTION_OSC_PORT_UDP", 0)

# === Configuration ===
LIB_PATH = carla_cfg.get("library_path", "/usr/lib/carla/libcarla_standalone2.so")
# Get absolute path to project file (relative to this script's directory)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
project_file = carla_cfg.get("project_file", "defaultProj.carxp")
PROJECT_PATH = os.path.join(SCRIPT_DIR, project_file)
AUDIO_DRIVER = carla_cfg.get("audio_driver", "JACK")
CLIENT_NAME = carla_cfg.get("client_name", "WebAppHost")
OSC_UDP_PORT = osc_cfg.get("udp_port", 28017)
OSC_TCP_PORT = osc_cfg.get("tcp_port", 5004)

# === Initialize Carla Host ===
print("Initializing Carla HostDLL...")
host = carla_backend.CarlaHostDLL(LIB_PATH, True)

# Initialize CarlaUtils for plugin discovery
# CarlaUtils uses libcarla_utils.so which is typically in the same directory as the main library
utils = None
utils_lib_paths = [
    LIB_PATH.replace("libcarla_standalone2.so", "libcarla_utils.so"),
    LIB_PATH.replace("libcarla_standalone2.so", "libcarla_utils2.so"),
    "/usr/lib/carla/libcarla_utils.so",
    "/usr/lib/carla/libcarla_utils2.so",
    "/usr/local/lib/carla/libcarla_utils.so",
    "/usr/local/lib/carla/libcarla_utils2.so",
]

for utils_lib_path in utils_lib_paths:
    if os.path.exists(utils_lib_path):
        try:
            utils = carla_utils.CarlaUtils(utils_lib_path)
            print(f"CarlaUtils initialized from: {utils_lib_path}")
            break
        except Exception as e:
            print(f"Warning: Could not load CarlaUtils from {utils_lib_path}: {e}")
            continue

if utils is None:
    print("Warning: Could not initialize CarlaUtils from any known location.")
    print("Plugin discovery will be limited. Continuing anyway...")
    print(f"Tried paths: {utils_lib_paths}")
driver_count = host.get_engine_driver_count()
print(f"HOST DRIVER COUNT: {driver_count}")
for i in range(driver_count):
    print(f"Driver {i}:")
    print(f"  Name: {host.get_engine_driver_name(i)}")
    print(f"  Devices: {host.get_engine_driver_device_names(i)}")

# Configure OSC (Open Sound Control) BEFORE initializing engine
# These options must be set before engine_init() for them to take effect
host.set_engine_option(ENGINE_OPTION_OSC_ENABLED, 1, "")
host.set_engine_option(ENGINE_OPTION_OSC_PORT_TCP, OSC_TCP_PORT, "")
host.set_engine_option(ENGINE_OPTION_OSC_PORT_UDP, OSC_UDP_PORT, "")

# Configure plugin paths BEFORE initializing engine
# Get plugin paths from config or use defaults
ENGINE_OPTION_PLUGIN_PATH = getattr(carla_backend, "ENGINE_OPTION_PLUGIN_PATH", 19)
PLUGIN_LV2 = getattr(carla_backend, "PLUGIN_LV2", 0)
PLUGIN_VST2 = getattr(carla_backend, "PLUGIN_VST2", 0)
PLUGIN_VST3 = getattr(carla_backend, "PLUGIN_VST3", 0)

# Get plugin paths from config
plugin_paths_cfg = carla_cfg.get("plugin_paths", {})
lv2_path = plugin_paths_cfg.get("lv2", os.getenv("LV2_PATH", "/usr/lib/lv2"))
vst2_path = plugin_paths_cfg.get("vst2", os.getenv("VST_PATH", "/usr/lib/vst"))
vst3_path = plugin_paths_cfg.get("vst3", os.getenv("VST3_PATH", "/usr/lib/vst3"))

# Set plugin paths
if lv2_path:
    host.set_engine_option(ENGINE_OPTION_PLUGIN_PATH, PLUGIN_LV2, lv2_path)
if vst2_path:
    host.set_engine_option(ENGINE_OPTION_PLUGIN_PATH, PLUGIN_VST2, vst2_path)
if vst3_path:
    host.set_engine_option(ENGINE_OPTION_PLUGIN_PATH, PLUGIN_VST3, vst3_path)

# Initialize the audio engine
ok = host.engine_init(AUDIO_DRIVER, CLIENT_NAME)
if not ok:
    print("Engine failed to start:", host.get_last_error())
    sys.exit(1)
print("Engine initialized successfully!")

loaded = host.load_project(PROJECT_PATH)
if not loaded:
    error_msg = host.get_last_error() or "Unknown error"
    print(f"Failed to load project: {error_msg}")
    sys.exit(1)
print("Project loaded successfully!")
print("Plugins in project:", host.get_current_plugin_count())


def _maybe_attr(module: Any, name: str, fallback: Any = None) -> Any:
    """Safely fetch an attribute from a module, returning fallback if missing."""
    if fallback is None:
        fallback = getattr(module, "PLUGIN_NONE", 0)
    return getattr(module, name, fallback)


def _maybe_option(module: Any, name: str) -> int:
    """Safely fetch plugin option constants, defaulting to 0."""
    return getattr(module, name, 0)


# ==== Display Plugin UI ====
host.show_custom_ui(0, True)


# === Plugin Database Loading ===
PLUGIN_DB_PATH = plugin_db_cfg.get("path")
PLUGIN_DATABASE: List[Dict[str, Any]] = []

# Cache for discovered plugins (not in database)
DISCOVERED_PLUGINS_CACHE: Dict[str, Dict[str, Any]] = {}

# Plugin chain tracking (list of plugin IDs in order)
PLUGIN_CHAIN: List[int] = []

# Binary type constants
BINARY_NATIVE = getattr(carla_backend, "BINARY_NATIVE", 0)

BACKEND_TYPE_MAP = {
    "PLUGIN_NONE": _maybe_attr(carla_backend, "PLUGIN_NONE", 0),
    "NONE": _maybe_attr(carla_backend, "PLUGIN_NONE", 0),
    "PLUGIN_INTERNAL": _maybe_attr(carla_backend, "PLUGIN_INTERNAL"),
    "INTERNAL": _maybe_attr(carla_backend, "PLUGIN_INTERNAL"),
    "PLUGIN_LADSPA": _maybe_attr(carla_backend, "PLUGIN_LADSPA"),
    "LADSPA": _maybe_attr(carla_backend, "PLUGIN_LADSPA"),
    "PLUGIN_DSSI": _maybe_attr(carla_backend, "PLUGIN_DSSI"),
    "DSSI": _maybe_attr(carla_backend, "PLUGIN_DSSI"),
    "PLUGIN_LV2": _maybe_attr(carla_backend, "PLUGIN_LV2"),
    "LV2": _maybe_attr(carla_backend, "PLUGIN_LV2"),
    "PLUGIN_VST2": _maybe_attr(carla_backend, "PLUGIN_VST2"),
    "VST2": _maybe_attr(carla_backend, "PLUGIN_VST2"),
    "PLUGIN_VST3": _maybe_attr(carla_backend, "PLUGIN_VST3"),
    "VST3": _maybe_attr(carla_backend, "PLUGIN_VST3"),
    "PLUGIN_AU": _maybe_attr(carla_backend, "PLUGIN_AU"),
    "AU": _maybe_attr(carla_backend, "PLUGIN_AU"),
    "PLUGIN_SF2": _maybe_attr(carla_backend, "PLUGIN_SF2"),
    "SF2": _maybe_attr(carla_backend, "PLUGIN_SF2"),
    "PLUGIN_SFZ": _maybe_attr(carla_backend, "PLUGIN_SFZ"),
    "SFZ": _maybe_attr(carla_backend, "PLUGIN_SFZ"),
    "PLUGIN_JSFX": _maybe_attr(carla_backend, "PLUGIN_JSFX"),
    "JSFX": _maybe_attr(carla_backend, "PLUGIN_JSFX"),
    "PLUGIN_JACK": _maybe_attr(carla_backend, "PLUGIN_JACK"),
    "JACK": _maybe_attr(carla_backend, "PLUGIN_JACK"),
    "PLUGIN_CLAP": _maybe_attr(carla_backend, "PLUGIN_CLAP"),
    "CLAP": _maybe_attr(carla_backend, "PLUGIN_CLAP"),
}

CATEGORY_MAP = {
    "PLUGIN_CATEGORY_NONE": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_NONE", 0),
    "NONE": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_NONE", 0),
    "PLUGIN_CATEGORY_SYNTH": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_SYNTH", 0),
    "SYNTH": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_SYNTH", 0),
    "PLUGIN_CATEGORY_DELAY": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DELAY", 0),
    "DELAY": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DELAY", 0),
    "PLUGIN_CATEGORY_EQ": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_EQ", 0),
    "EQ": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_EQ", 0),
    "PLUGIN_CATEGORY_FILTER": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_FILTER", 0),
    "FILTER": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_FILTER", 0),
    "PLUGIN_CATEGORY_DISTORTION": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DISTORTION", 0),
    "DISTORTION": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DISTORTION", 0),
    "PLUGIN_CATEGORY_DYNAMICS": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DYNAMICS", 0),
    "DYNAMICS": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_DYNAMICS", 0),
    "PLUGIN_CATEGORY_MODULATOR": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_MODULATOR", 0),
    "MODULATOR": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_MODULATOR", 0),
    "PLUGIN_CATEGORY_UTILITY": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_UTILITY", 0),
    "UTILITY": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_UTILITY", 0),
    "PLUGIN_CATEGORY_OTHER": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_OTHER", 0),
    "OTHER": _maybe_attr(carla_backend, "PLUGIN_CATEGORY_OTHER", 0),
}

OPTION_MAP = {
    "PLUGIN_OPTION_FIXED_BUFFERS": _maybe_option(carla_backend, "PLUGIN_OPTION_FIXED_BUFFERS"),
    "PLUGIN_OPTION_FORCE_STEREO": _maybe_option(carla_backend, "PLUGIN_OPTION_FORCE_STEREO"),
    "PLUGIN_OPTION_MAP_PROGRAM_CHANGES": _maybe_option(carla_backend, "PLUGIN_OPTION_MAP_PROGRAM_CHANGES"),
    "PLUGIN_OPTION_USE_CHUNKS": _maybe_option(carla_backend, "PLUGIN_OPTION_USE_CHUNKS"),
    "PLUGIN_OPTION_SEND_CONTROL_CHANGES": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_CONTROL_CHANGES"),
    "PLUGIN_OPTION_SEND_CHANNEL_PRESSURE": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_CHANNEL_PRESSURE"),
    "PLUGIN_OPTION_SEND_NOTE_AFTERTOUCH": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_NOTE_AFTERTOUCH"),
    "PLUGIN_OPTION_SEND_PITCHBEND": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_PITCHBEND"),
    "PLUGIN_OPTION_SEND_ALL_SOUND_OFF": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_ALL_SOUND_OFF"),
    "PLUGIN_OPTION_SEND_PROGRAM_CHANGES": _maybe_option(carla_backend, "PLUGIN_OPTION_SEND_PROGRAM_CHANGES"),
    "PLUGIN_OPTION_SKIP_SENDING_NOTES": _maybe_option(carla_backend, "PLUGIN_OPTION_SKIP_SENDING_NOTES"),
}


def _resolve_path(path_value: str) -> str:
    """Resolve a config path relative to project root and expand user/home."""
    if not path_value:
        return ""
    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(PROJECT_ROOT, expanded)


# ============================================
# JACK Connection Management
# ============================================

def get_plugin_jack_port_name(plugin_id: int, is_output: bool, channel: int = 0) -> str:
    """Get JACK port name for a plugin's audio port"""
    try:
        plugin_info = host.get_plugin_info(plugin_id)
        plugin_name = plugin_info.get("name", f"plugin_{plugin_id}")
        
        # Carla uses format: plugin_name:output_1 or plugin_name:input_1
        # Based on actual JACK port names like "ADLplug:output_1", "3 Band EQ:input_1"
        if is_output:
            if channel == 0:
                return f"{plugin_name}:output_1"
            else:
                return f"{plugin_name}:output_{channel + 1}"
        else:
            if channel == 0:
                return f"{plugin_name}:input_1"
            else:
                return f"{plugin_name}:input_{channel + 1}"
    except Exception as e:
        print(f"Error getting port name for plugin {plugin_id}: {e}")
        return ""

def get_plugin_audio_port_count(plugin_id: int) -> Dict[str, int]:
    """Get audio input and output count for a plugin"""
    try:
        plugin_info = host.get_plugin_info(plugin_id)
        # Try to get from plugin info, fallback to checking JACK ports
        return {
            "inputs": plugin_info.get("audioIns", 2),  # Default to stereo
            "outputs": plugin_info.get("audioOuts", 2)
        }
    except Exception as e:
        print(f"Error getting port count for plugin {plugin_id}: {e}")
        return {"inputs": 2, "outputs": 2}

def jack_connect(source: str, destination: str) -> bool:
    """Connect two JACK ports"""
    try:
        result = subprocess.run(
            ["jack_connect", source, destination],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            print(f"Connected: {source} -> {destination}")
            return True
        else:
            # Connection might already exist, which is OK
            if "already connected" in result.stderr.lower() or "already connected" in result.stdout.lower():
                print(f"Already connected: {source} -> {destination}")
                return True
            print(f"Failed to connect {source} -> {destination}: {result.stderr}")
            return False
    except Exception as e:
        print(f"Error connecting JACK ports: {e}")
        return False

def jack_disconnect(source: str, destination: str) -> bool:
    """Disconnect two JACK ports"""
    try:
        result = subprocess.run(
            ["jack_disconnect", source, destination],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            print(f"Disconnected: {source} -> {destination}")
            return True
        else:
            # Disconnection might not exist, which is OK
            if "not connected" in result.stderr.lower():
                print(f"Not connected: {source} -> {destination}")
                return True
            print(f"Failed to disconnect {source} -> {destination}: {result.stderr}")
            return False
    except Exception as e:
        print(f"Error disconnecting JACK ports: {e}")
        return False

def disconnect_plugin_chain(prev_plugin_id: int, next_plugin_id: int):
    """Disconnect all audio connections between two plugins"""
    prev_ports = get_plugin_audio_port_count(prev_plugin_id)
    next_ports = get_plugin_audio_port_count(next_plugin_id)
    
    # Disconnect all output channels of prev_plugin to all input channels of next_plugin
    max_channels = min(prev_ports["outputs"], next_ports["inputs"])
    
    for ch in range(max_channels):
        source = get_plugin_jack_port_name(prev_plugin_id, is_output=True, channel=ch)
        dest = get_plugin_jack_port_name(next_plugin_id, is_output=False, channel=ch)
        
        if source and dest:
            jack_disconnect(source, dest)

def connect_plugin_chain(prev_plugin_id: int, next_plugin_id: int):
    """Connect all audio outputs of prev_plugin to inputs of next_plugin"""
    prev_ports = get_plugin_audio_port_count(prev_plugin_id)
    next_ports = get_plugin_audio_port_count(next_plugin_id)
    
    # Connect matching channels (output 1 -> input 1, output 2 -> input 2)
    max_channels = min(prev_ports["outputs"], next_ports["inputs"])
    
    print(f"Connecting plugin {prev_plugin_id} -> {next_plugin_id} ({max_channels} channels)")
    
    for ch in range(max_channels):
        source = get_plugin_jack_port_name(prev_plugin_id, is_output=True, channel=ch)
        dest = get_plugin_jack_port_name(next_plugin_id, is_output=False, channel=ch)
        
        print(f"  Channel {ch}: {source} -> {dest}")
        
        if source and dest:
            # Wait a bit for ports to be available
            time.sleep(0.1)
            jack_connect(source, dest)
        else:
            print(f"  WARNING: Missing port names (source={source}, dest={dest})")

def connect_final_plugin_to_system(plugin_id: int):
    """Connect final plugin outputs to system playback"""
    plugin_ports = get_plugin_audio_port_count(plugin_id)
    
    # Connect output 1 -> system:playback_1, output 2 -> system:playback_2
    for ch in range(min(plugin_ports["outputs"], 2)):
        source = get_plugin_jack_port_name(plugin_id, is_output=True, channel=ch)
        dest = f"system:playback_{ch + 1}"
        
        if source:
            time.sleep(0.1)
            jack_connect(source, dest)
            
def disconnect_final_plugin_from_system(plugin_id: int):
    """Disconnect plugin outputs from system playback"""
    plugin_ports = get_plugin_audio_port_count(plugin_id)
    
    # Disconnect output 1 -> system:playback_1, output 2 -> system:playback_2
    for ch in range(min(plugin_ports["outputs"], 2)):
        source = get_plugin_jack_port_name(plugin_id, is_output=True, channel=ch)
        dest = f"system:playback_{ch + 1}"
        
        if source:
            jack_disconnect(source, dest)

def get_plugin_actual_connections(plugin_id: int) -> List[tuple]:
    """Get actual JACK connections for a plugin by querying jack_lsp"""
    connections = []
    try:
        plugin_info = host.get_plugin_info(plugin_id)
        plugin_name = plugin_info.get("name", f"plugin_{plugin_id}")
        
        # Get all ports and their connections
        result = subprocess.run(
            ["jack_lsp", "-c"],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            current_port = None
            for line in lines:
                line = line.strip()
                if not line:
                    current_port = None
                    continue
                if line.startswith(plugin_name + ':'):
                    current_port = line
                elif current_port and line and not line.startswith(plugin_name + ':'):
                    # This is a connection (indented or following the port)
                    dest_port = line.strip()
                    if dest_port:
                        connections.append((current_port, dest_port))
        
    except Exception as e:
        print(f"Error getting connections for plugin {plugin_id}: {e}")
    
    return connections

def disconnect_plugin_completely(plugin_id: int):
    """Disconnect a plugin from all its actual JACK connections"""
    # First, get actual connections using jack_lsp
    connections = get_plugin_actual_connections(plugin_id)
    
    # Disconnect all found connections
    for source, dest in connections:
        print(f"Disconnecting actual connection: {source} -> {dest}")
        jack_disconnect(source, dest)
    
    # Also disconnect from system explicitly (in case jack_lsp missed it)
    disconnect_final_plugin_from_system(plugin_id)

def reroute_plugin_chain(insert_position: int, new_plugin_id: int):
    """
    Reroute JACK connections when a plugin is inserted.
    
    If plugin chain was: A -> B (at positions 0 -> 1)
    And we insert C at position 1, the chain becomes: A -> C -> B
    So we need to:
    1. Disconnect A -> B
    2. Connect A -> C
    3. Connect C -> B
    """
    global PLUGIN_CHAIN
    
    # Wait a moment for plugin to fully initialize
    time.sleep(0.2)
    
    # Update plugin chain - insert new plugin at specified position
    if insert_position < 0:
        insert_position = 0
    if insert_position > len(PLUGIN_CHAIN):
        insert_position = len(PLUGIN_CHAIN)
    
    # If inserting in the middle, disconnect the connection we're breaking
    if insert_position > 0 and insert_position < len(PLUGIN_CHAIN):
        prev_plugin_id = PLUGIN_CHAIN[insert_position - 1]
        next_plugin_id = PLUGIN_CHAIN[insert_position] if insert_position < len(PLUGIN_CHAIN) else None
        
        if next_plugin_id is not None:
            print(f"Disconnecting plugin {prev_plugin_id} -> {next_plugin_id}")
            disconnect_plugin_chain(prev_plugin_id, next_plugin_id)
    
    # Insert new plugin into chain
    PLUGIN_CHAIN.insert(insert_position, new_plugin_id)
    
    # Connect new plugin to previous plugin (if exists)
    if insert_position > 0:
        prev_plugin_id = PLUGIN_CHAIN[insert_position - 1]
        print(f"Connecting plugin {prev_plugin_id} -> {new_plugin_id}")
        connect_plugin_chain(prev_plugin_id, new_plugin_id)
    
    # Connect new plugin to next plugin (if exists)
    if insert_position < len(PLUGIN_CHAIN) - 1:
        next_plugin_id = PLUGIN_CHAIN[insert_position + 1]
        print(f"Connecting plugin {new_plugin_id} -> {next_plugin_id}")
        connect_plugin_chain(new_plugin_id, next_plugin_id)

def sync_plugin_chain():
    """Sync PLUGIN_CHAIN with actual loaded plugins and ensure final plugin is connected to system"""
    global PLUGIN_CHAIN
    count = host.get_current_plugin_count()
    
    # Only reset if chain is empty, wrong length, or contains invalid plugin IDs
    # Otherwise preserve the current order (allows manual rearrangements)
    if len(PLUGIN_CHAIN) == 0 or len(PLUGIN_CHAIN) != count:
        PLUGIN_CHAIN = list(range(count))
    else:
        # Verify all plugin IDs in chain are valid (0 to count-1)
        valid_plugin_ids = set(range(count))
        if not all(pid in valid_plugin_ids for pid in PLUGIN_CHAIN):
            # Chain contains invalid IDs, reset it
            PLUGIN_CHAIN = list(range(count))
        # If chain is valid, preserve the order
    
    # Ensure final plugin is connected to system playback
    if len(PLUGIN_CHAIN) > 0:
        final_plugin_id = PLUGIN_CHAIN[-1]
        connect_final_plugin_to_system(final_plugin_id)
    
    print(f"Synced plugin chain: {PLUGIN_CHAIN}")


def load_plugin_database() -> None:
    """Load plugin database from configured path."""
    global PLUGIN_DATABASE
    if not PLUGIN_DB_PATH:
        print("No plugin database path configured; plugin addition disabled.")
        PLUGIN_DATABASE = []
        return

    db_path = _resolve_path(PLUGIN_DB_PATH)
    if not os.path.exists(db_path):
        print(f"Plugin database file not found at {db_path}; plugin addition disabled.")
        PLUGIN_DATABASE = []
        return

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            PLUGIN_DATABASE = data.get("plugins", [])
        elif isinstance(data, list):
            PLUGIN_DATABASE = data
        else:
            print(f"Unexpected plugin database format in {db_path}; expected list or dict.")
            PLUGIN_DATABASE = []
    except Exception as exc:
        print(f"Failed to load plugin database from {db_path}: {exc}")
        PLUGIN_DATABASE = []


load_plugin_database()

# Initialize plugin chain on startup
sync_plugin_chain()

# === Keep the engine alive ===
def idle_loop():
    """Keeps the Carla engine responsive."""
    while True:
        try:
            host.engine_idle()
            time.sleep(0.05)  # run ~20 times per second
        except Exception as e:
            print("Idle loop stopped:", e)
            break

threading.Thread(target=idle_loop, daemon=True).start()

# === Flask app ===
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    """API information and available endpoints"""
    return jsonify({
        "name": "Carla Startup API",
        "version": "1.0",
        "endpoints": {
            "GET /plugins": "List all loaded plugins",
            "GET /plugins/<id>/parameters": "List parameters for a plugin",
            "POST /plugins/set_parameter": "Set a parameter value (body: {plugin_id, param_id, value})",
            "GET /plugin-db": "List available plugins from configured database",
            "GET /plugins/discover": "Discover available plugins from configured plugin paths",
            "POST /plugins/add": "Add a plugin from the database (body: {plugin_id})",
            "GET /plugins/chain": "Get the current plugin chain order",
            "POST /plugins/move": "Move a plugin up/down in chain (body: {plugin_id, direction: 'up'|'down'})",
            "POST /reload_project": "Reload the Carla project (optional body: {path})",
            "POST /shutdown": "Shutdown the Carla engine"
        }
    })

@app.route("/plugins", methods=["GET"])
def list_plugins():
    """List all loaded plugins"""
    sync_plugin_chain()  # Sync chain when listing
    plugins = []
    count = host.get_current_plugin_count()
    for i in range(count):
        info = host.get_plugin_info(i)
        plugins.append({
            "id": i,
            "name": info.get("name", ""),
            "label": info.get("label", ""),
            "chain_position": PLUGIN_CHAIN.index(i) if i in PLUGIN_CHAIN else -1
        })
    return jsonify({"plugins": plugins})

@app.route("/plugins/<int:plugin_id>/parameters", methods=["GET"])
def list_parameters(plugin_id):
    """List parameters for a given plugin"""
    try:
        plugin_count = host.get_current_plugin_count()
        if plugin_id < 0 or plugin_id >= plugin_count:
            return jsonify({"error": f"Invalid plugin_id: {plugin_id}. Valid range: 0-{plugin_count-1}"}), 400
        
        params = []
        n_params = host.get_parameter_count(plugin_id)
        for pid in range(n_params):
            pinfo = host.get_parameter_info(plugin_id, pid)
            prange = host.get_parameter_ranges(plugin_id, pid)
            value = host.get_current_parameter_value(plugin_id, pid)
            params.append({
                "id": pid,
                "name": pinfo.get("name", "") if pinfo else "",
                "min": prange.get("min", 0.0) if prange else 0.0,
                "max": prange.get("max", 1.0) if prange else 1.0,
                "value": value
            })
        return jsonify({"plugin_id": plugin_id, "parameters": params})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/plugins/set_parameter", methods=["POST"])
def set_parameter():
    """Set parameter value for a plugin"""
    try:
        data = request.get_json(force=True)
        plugin_id = int(data["plugin_id"])
        param_id = int(data["param_id"])
        value = float(data["value"])
        
        # Validate plugin_id
        plugin_count = host.get_current_plugin_count()
        if plugin_id < 0 or plugin_id >= plugin_count:
            return jsonify({"error": f"Invalid plugin_id: {plugin_id}"}), 400
        
        # Validate param_id
        param_count = host.get_parameter_count(plugin_id)
        if param_id < 0 or param_id >= param_count:
            return jsonify({"error": f"Invalid param_id: {param_id} for plugin {plugin_id}"}), 400
        
        host.set_parameter_value(plugin_id, param_id, value)
        return jsonify({"status": "ok", "plugin_id": plugin_id, "param_id": param_id, "value": value})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid request data: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/reload_project", methods=["POST"])
def reload_project():
    """Reload the Carla project"""
    try:
        data = request.get_json(force=True) if request.is_json else {}
        project_path = data.get("path", PROJECT_PATH)
        
        # If relative path, make it relative to script directory
        if not os.path.isabs(project_path):
            project_path = os.path.join(SCRIPT_DIR, project_path)
        
        # load_project accepts string, not bytes (based on test.py line 13)
        success = host.load_project(project_path)
        if not success:
            error_msg = host.get_last_error() or "Unknown error"
            return jsonify({"status": False, "error": error_msg}), 500
        return jsonify({"status": True, "path": project_path})
    except Exception as e:
        return jsonify({"status": False, "error": str(e)}), 500

@app.route("/plugin-db", methods=["GET"])
def plugin_database():
    """Return the configured plugin database entries."""
    if not PLUGIN_DATABASE:
        return jsonify({"plugins": [], "warning": "Plugin database not configured or empty."})

    entries = []
    for entry in PLUGIN_DATABASE:
        entries.append({
            "id": entry.get("id"),
            "display_name": entry.get("display_name", entry.get("name", entry.get("label", "Unnamed Plugin"))),
            "description": entry.get("description", ""),
            "backend_type": entry.get("backend_type"),
            "category": entry.get("category"),
        })
    return jsonify({"plugins": entries})


@app.route("/plugins/discover", methods=["GET"])
def discover_plugins():
    """Discover available plugins from configured plugin paths using Carla's discovery system."""
    try:
        if utils is None:
            return jsonify({
                "error": "CarlaUtils not available. Plugin discovery requires libcarla_utils.so",
                "plugins": []
            }), 503
        
        discovered_plugins = []
        
        # Plugin types that support cached discovery
        discoverable_types = {
            "PLUGIN_INTERNAL": carla_backend.PLUGIN_INTERNAL,
            "PLUGIN_LV2": carla_backend.PLUGIN_LV2,
            "PLUGIN_JSFX": getattr(carla_backend, "PLUGIN_JSFX", None),
            "PLUGIN_SFZ": getattr(carla_backend, "PLUGIN_SFZ", None),
        }
        
        # Get plugin paths from config or environment variables
        plugin_paths_cfg = carla_cfg.get("plugin_paths", {})
        
        plugin_paths = {
            "PLUGIN_LV2": plugin_paths_cfg.get("lv2", os.getenv("LV2_PATH", "/usr/lib/lv2")),
            "PLUGIN_JSFX": plugin_paths_cfg.get("jsfx", os.getenv("JSFX_PATH", "")),
            "PLUGIN_SFZ": plugin_paths_cfg.get("sfz", os.getenv("SFZ_PATH", "")),
        }
        
        for type_name, type_id in discoverable_types.items():
            if type_id is None:
                continue
                
            plugin_path = plugin_paths.get(type_name, "")
            
            try:
                count = utils.get_cached_plugin_count(type_id, plugin_path)
                
                for i in range(count):
                    try:
                        info = utils.get_cached_plugin_info(type_id, i)
                        
                        if not info or not info.get("valid", False):
                            continue
                        
                        # Extract plugin information
                        label = info.get("label", "")
                        name = info.get("name", label)
                        
                        if not label:
                            continue
                        
                        # Generate unique ID
                        plugin_id = f"{type_name.lower()}_{label.replace('/', '_').replace(' ', '_').lower()}"
                        plugin_id = plugin_id.replace("plugin_", "").replace("__", "_")
                        
                        # Map category ID to category name
                        category_id = info.get("category", 0)
                        category_name = "PLUGIN_CATEGORY_NONE"
                        for cat_name, cat_id in CATEGORY_MAP.items():
                            if isinstance(cat_id, int) and cat_id == category_id:
                                category_name = cat_name
                                break
                        
                        plugin_entry = {
                            "id": plugin_id,
                            "display_name": name or label,
                            "description": info.get("maker", ""),
                            "backend_type": type_name,
                            "category": category_name,
                            "filename": info.get("filename", ""),
                            "name": name or "",
                            "label": label,
                            "unique_id": int(info.get("uniqueId", 0)),
                            "audio_ins": info.get("audioIns", 0),
                            "audio_outs": info.get("audioOuts", 0),
                            "midi_ins": info.get("midiIns", 0),
                            "midi_outs": info.get("midiOuts", 0),
                            "parameters_ins": info.get("parameterIns", 0),
                            "parameters_outs": info.get("parameterOuts", 0),
                        }
                        discovered_plugins.append(plugin_entry)
                        # Cache discovered plugins for later use in add_plugin
                        DISCOVERED_PLUGINS_CACHE[plugin_id] = plugin_entry
                    except Exception as e:
                        print(f"Error getting info for {type_name} plugin {i}: {e}")
                        continue
                        
            except Exception as e:
                print(f"Error discovering {type_name} plugins: {e}")
                continue
        
        # Sort by type and name
        discovered_plugins.sort(key=lambda x: (x["backend_type"], x["display_name"]))
        
        return jsonify({
            "plugins": discovered_plugins,
            "count": len(discovered_plugins),
            "message": f"Discovered {len(discovered_plugins)} plugins from configured paths"
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "plugins": []}), 500


def _normalize_backend_type(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        key = value.strip().upper()
        return BACKEND_TYPE_MAP.get(key, BACKEND_TYPE_MAP.get(f"PLUGIN_{key}", carla_backend.PLUGIN_NONE))
    return carla_backend.PLUGIN_NONE


def _normalize_category(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        key = value.strip().upper()
        return CATEGORY_MAP.get(key, CATEGORY_MAP.get(f"PLUGIN_CATEGORY_{key}", carla_backend.PLUGIN_CATEGORY_NONE))
    return carla_backend.PLUGIN_CATEGORY_NONE


def _normalize_options(options: Any) -> int:
    if not options:
        return 0
    if isinstance(options, int):
        return options
    if isinstance(options, list):
        bitmask = 0
        for item in options:
            if isinstance(item, int):
                bitmask |= item
            elif isinstance(item, str):
                key = item.strip().upper()
                bitmask |= OPTION_MAP.get(key, OPTION_MAP.get(f"PLUGIN_OPTION_{key}", 0))
        return bitmask
    return 0


def _find_plugin_entry(plugin_id: str) -> Dict[str, Any]:
    """Find plugin entry in database or discovered plugins cache."""
    # First check the database
    for entry in PLUGIN_DATABASE:
        if entry.get("id") == plugin_id:
            return entry
    # Then check discovered plugins cache
    if plugin_id in DISCOVERED_PLUGINS_CACHE:
        return DISCOVERED_PLUGINS_CACHE[plugin_id]
    return {}


@app.route("/plugins/add", methods=["POST"])
def add_plugin():
    """Add a new plugin from the plugin database or discovered plugins to the current project."""
    try:
        data = request.get_json(force=True)
        plugin_id = data.get("plugin_id")
        
        if not plugin_id:
            return jsonify({"error": "plugin_id is required"}), 400

        entry = _find_plugin_entry(plugin_id)
        if not entry:
            return jsonify({"error": f"Plugin id '{plugin_id}' not found in database or discovered plugins. Try discovering plugins first."}), 404

        backend_type = _normalize_backend_type(entry.get("backend_type", carla_backend.PLUGIN_INTERNAL))
        category = _normalize_category(entry.get("category", carla_backend.PLUGIN_CATEGORY_NONE))
        filename = entry.get("filename", "") or ""
        name = entry.get("name", "")
        label = entry.get("label", "")
        unique_id = int(entry.get("unique_id", 0))
        options = _normalize_options(entry.get("options", []))

        # Determine binary type - INTERNAL, LV2, SF2, SFZ, JACK must use BINARY_NATIVE
        # For VST2/VST3/CLAP/AU, we also use BINARY_NATIVE (native architecture)
        btype = BINARY_NATIVE

        success = host.add_plugin(
            btype,           # Binary type (BINARY_NATIVE for native plugins)
            backend_type,    # Plugin type (PLUGIN_INTERNAL, PLUGIN_LV2, etc.)
            filename,        # Plugin filename/path
            name,            # Plugin name
            label,           # Plugin label
            unique_id,       # Plugin unique ID
            None,           # Extra pointer (not used for most plugin types)
            options,        # Plugin options
        )

        if not success:
            error_msg = host.get_last_error() or "Unknown error while adding plugin"
            return jsonify({"error": error_msg}), 500

        new_plugin_index = host.get_current_plugin_count() - 1
        plugin_info = host.get_plugin_info(new_plugin_index)
        
        # Handle plugin chain rerouting - only append to end for now
        # Get the previous final plugin BEFORE the new plugin was added
        # The new plugin is at index = current_count - 1, so previous plugins are 0 to current_count - 2
        prev_final_plugin_id = None
        
        # Sync to get current chain state (this will include the new plugin)
        sync_plugin_chain()
        
        # Find the previous final plugin (the one before the new plugin)
        if len(PLUGIN_CHAIN) > 1:
            # The new plugin should be at the end, so previous is second-to-last
            prev_final_plugin_id = PLUGIN_CHAIN[-2]
        
        # If there was a previous final plugin, disconnect it from system and connect to new plugin
        if prev_final_plugin_id is not None and prev_final_plugin_id != new_plugin_index:
            # Get plugin names for debugging
            try:
                prev_info = host.get_plugin_info(prev_final_plugin_id)
                new_info = host.get_plugin_info(new_plugin_index)
                prev_name = prev_info.get("name", f"plugin_{prev_final_plugin_id}")
                new_name = new_info.get("name", f"plugin_{new_plugin_index}")
                print(f"Previous final plugin: {prev_name} (ID {prev_final_plugin_id})")
                print(f"New plugin: {new_name} (ID {new_plugin_index})")
            except:
                pass
            
            print(f"Disconnecting previous final plugin {prev_final_plugin_id} from system playback")
            disconnect_final_plugin_from_system(prev_final_plugin_id)
            print(f"Connecting previous plugin {prev_final_plugin_id} -> new plugin {new_plugin_index}")
            # Wait a moment for ports to be available
            time.sleep(0.3)
            connect_plugin_chain(prev_final_plugin_id, new_plugin_index)
        else:
            if prev_final_plugin_id == new_plugin_index:
                print(f"ERROR: prev_final_plugin_id ({prev_final_plugin_id}) == new_plugin_index ({new_plugin_index}) - skipping connection")
            else:
                print(f"No previous plugin found (chain length: {len(PLUGIN_CHAIN)})")
        
        # Connect final plugin to system playback
        print(f"Connecting final plugin {new_plugin_index} to system playback")
        time.sleep(0.2)
        connect_final_plugin_to_system(new_plugin_index)
        
        return jsonify({
            "status": "ok", 
            "plugin": plugin_info, 
            "plugin_id": new_plugin_index,
            "chain_position": len(PLUGIN_CHAIN) - 1
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/plugins/chain", methods=["GET"])
def get_plugin_chain():
    """Get the current plugin chain order"""
    sync_plugin_chain()
    chain_info = []
    for idx, plugin_id in enumerate(PLUGIN_CHAIN):
        try:
            plugin_info = host.get_plugin_info(plugin_id)
            chain_info.append({
                "position": idx,
                "plugin_id": plugin_id,
                "name": plugin_info.get("name", ""),
                "label": plugin_info.get("label", "")
            })
        except:
            continue
    return jsonify({"chain": chain_info})

@app.route("/plugins/move", methods=["POST"])
def move_plugin():
    """Move a plugin up or down in the processing chain"""
    try:
        data = request.get_json(force=True)
        plugin_id = int(data.get("plugin_id"))
        direction = data.get("direction", "up")  # "up" or "down"
        
        sync_plugin_chain()
        
        if plugin_id not in PLUGIN_CHAIN:
            return jsonify({"error": f"Plugin {plugin_id} not found in chain"}), 404
        
        current_position = PLUGIN_CHAIN.index(plugin_id)
        new_position = current_position + (1 if direction == "down" else -1)
        
        # Validate new position
        if new_position < 0 or new_position >= len(PLUGIN_CHAIN):
            return jsonify({"error": f"Cannot move plugin {direction} - already at edge"}), 400
        
        # Get adjacent plugins BEFORE moving (for disconnecting)
        prev_plugin = PLUGIN_CHAIN[current_position - 1] if current_position > 0 else None
        next_plugin = PLUGIN_CHAIN[current_position + 1] if current_position < len(PLUGIN_CHAIN) - 1 else None
        
        # Identify the plugin that will be displaced (the one currently at new_position)
        displaced_plugin = PLUGIN_CHAIN[new_position] if new_position < len(PLUGIN_CHAIN) else None
        
        print(f"Moving plugin {plugin_id} from position {current_position} to {new_position}")
        print(f"  prev_plugin: {prev_plugin}, next_plugin: {next_plugin}, displaced_plugin: {displaced_plugin}")
        
        # Disconnect ALL connections involving the plugin being moved
        if prev_plugin is not None:
            print(f"Disconnecting {prev_plugin} -> {plugin_id}")
            disconnect_plugin_chain(prev_plugin, plugin_id)
        if next_plugin is not None:
            print(f"Disconnecting {plugin_id} -> {next_plugin}")
            disconnect_plugin_chain(plugin_id, next_plugin)
        
        # If moving from last position, disconnect from system
        if current_position == len(PLUGIN_CHAIN) - 1:
            print(f"Disconnecting {plugin_id} from system (was last)")
            disconnect_final_plugin_from_system(plugin_id)
        
        # Disconnect the displaced plugin completely
        # The displaced plugin is at new_position, and will be moved when we insert
        if displaced_plugin is not None and displaced_plugin != plugin_id:
            # If displaced plugin is currently last, disconnect from system FIRST
            if new_position == len(PLUGIN_CHAIN) - 1:
                print(f"Disconnecting {displaced_plugin} from system (was last, will be displaced)")
                disconnect_final_plugin_from_system(displaced_plugin)
            
            # Find what the displaced plugin is currently connected to (in OLD chain)
            # Note: displaced_prev might be the plugin we're moving if moving down
            displaced_prev = PLUGIN_CHAIN[new_position - 1] if new_position > 0 else None
            displaced_next = PLUGIN_CHAIN[new_position + 1] if new_position < len(PLUGIN_CHAIN) - 1 else None
            
            # Disconnect from previous (but not if it's the plugin we're moving, we already did that)
            if displaced_prev is not None and displaced_prev != plugin_id:
                print(f"Disconnecting {displaced_prev} -> {displaced_plugin} (displaced plugin)")
                disconnect_plugin_chain(displaced_prev, displaced_plugin)
            
            # Disconnect from next
            if displaced_next is not None:
                print(f"Disconnecting {displaced_plugin} -> {displaced_next} (displaced plugin)")
                disconnect_plugin_chain(displaced_plugin, displaced_next)
            
            # Also completely disconnect to be safe (handles any missed connections)
            print(f"Completely disconnecting {displaced_plugin} to ensure clean state")
            disconnect_plugin_completely(displaced_plugin)
        
        # Move plugin in chain
        PLUGIN_CHAIN.remove(plugin_id)
        PLUGIN_CHAIN.insert(new_position, plugin_id)
        print(f"Chain after move: {PLUGIN_CHAIN}")
        
        # Wait a moment for disconnections to complete
        time.sleep(0.3)
        
        # NOW get the adjacent plugins AFTER moving (for reconnecting)
        new_prev_plugin = PLUGIN_CHAIN[new_position - 1] if new_position > 0 else None
        new_next_plugin = PLUGIN_CHAIN[new_position + 1] if new_position < len(PLUGIN_CHAIN) - 1 else None
        
        print(f"  new_prev_plugin: {new_prev_plugin}, new_next_plugin: {new_next_plugin}")
        
        # IMPORTANT: Disconnect any plugins that are no longer final from system
        # Check all plugins except the one that should be final (the last in chain)
        final_plugin_id = PLUGIN_CHAIN[-1]
        for check_id in PLUGIN_CHAIN:
            if check_id != final_plugin_id:
                print(f"Ensuring plugin {check_id} is disconnected from system (not final)")
                disconnect_final_plugin_from_system(check_id)
        
        # CRITICAL FIX: Ensure prev_plugin is completely disconnected from the moved plugin
        # This handles cases where the initial disconnect didn't catch all connections
        # When swapping adjacent plugins, prev_plugin might still be connected to the moved plugin
        if prev_plugin is not None:
            print(f"Double-checking {prev_plugin} is completely disconnected from {plugin_id}")
            disconnect_plugin_chain(prev_plugin, plugin_id)
            # Also disconnect any other connections from prev_plugin to be safe
            disconnect_plugin_completely(prev_plugin)
        
        # Reconnect the gap left by moving the plugin FIRST
        # The gap is between prev_plugin and next_plugin (if both exist)
        if prev_plugin is not None and next_plugin is not None:
            # There's a gap to reconnect: prev_plugin -> next_plugin
            # But first, make sure next_plugin is disconnected from system
            print(f"Ensuring {next_plugin} is disconnected from system before filling gap")
            disconnect_final_plugin_from_system(next_plugin)
            print(f"Filling gap: {prev_plugin} -> {next_plugin}")
            time.sleep(0.2)
            connect_plugin_chain(prev_plugin, next_plugin)
        elif prev_plugin is not None and next_plugin is None:
            # We moved from last position, prev_plugin is now last
            print(f"Previous plugin {prev_plugin} is now final")
            time.sleep(0.2)
            connect_final_plugin_to_system(prev_plugin)
        
        # Reconnect the moved plugin in its new position
        if new_prev_plugin is not None:
            print(f"Connecting {new_prev_plugin} -> {plugin_id} (moved plugin)")
            time.sleep(0.2)
            connect_plugin_chain(new_prev_plugin, plugin_id)
        if new_next_plugin is not None:
            print(f"Connecting {plugin_id} -> {new_next_plugin} (moved plugin)")
            time.sleep(0.2)
            connect_plugin_chain(plugin_id, new_next_plugin)
        else:
            # This is now the final plugin - connect to system
            print(f"Connecting {plugin_id} -> system (moved plugin is now final)")
            time.sleep(0.2)
            connect_final_plugin_to_system(plugin_id)
        
        # CRITICAL: Always ensure the final plugin in the chain is connected to system playback
        # This is a safety net to catch any edge cases
        if len(PLUGIN_CHAIN) > 0:
            final_plugin_id = PLUGIN_CHAIN[-1]
            print(f"Ensuring final plugin {final_plugin_id} is connected to system playback")
            time.sleep(0.1)
            connect_final_plugin_to_system(final_plugin_id)
            jack_connect("a2j:AKM320 [24] (capture): AKM320 MIDI 1", "ADLplug:events-in")

        
        return jsonify({
            "status": "ok",
            "plugin_id": plugin_id,
            "old_position": current_position,
            "new_position": new_position
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Gracefully close the Carla engine"""
    try:
        host.engine_close()
        print("Engine closed cleanly.")
    finally:
        func = request.environ.get("werkzeug.server.shutdown")
        if func:
            func()
    return jsonify({"status": "engine closed"})

# === Run server ===
if __name__ == "__main__":
    print ("PYTHON_READY", flush=True)
    api_host = api_cfg.get("host", "0.0.0.0")
    api_port = api_cfg.get("port", 8080)
    app.run(host=api_host, port=api_port)
    host.show_custom_ui(0, True)
    time.sleep(99999)
