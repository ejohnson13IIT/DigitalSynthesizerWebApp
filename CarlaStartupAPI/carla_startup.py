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


# === Plugin Database Loading ===
PLUGIN_DB_PATH = plugin_db_cfg.get("path")
PLUGIN_DATABASE: List[Dict[str, Any]] = []

# Cache for discovered plugins (not in database)
DISCOVERED_PLUGINS_CACHE: Dict[str, Dict[str, Any]] = {}

# Audio chain: [a2j, plugin_id1, plugin_id2, ..., system]
# Index 0 = a2j midi bridge (input)
# Middle indices = plugin IDs in processing order
# Final index = system playback (output)
AUDIO_CHAIN: List[Any] = ["a2j", "system"]  # Start with just input and output

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

def disconnect_all_audio_connections():
    """Disconnect all audio connections in the chain"""
    # Get all actual connections using jack_lsp and disconnect them
    try:
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
                # Port name (not indented)
                if line and not line.startswith(' '):
                    current_port = line
                # Connection (indented)
                elif current_port and line.startswith(' '):
                    dest_port = line.strip()
                    if dest_port:
                        print(f"Disconnecting: {current_port} -> {dest_port}")
                        jack_disconnect(current_port, dest_port)
    except Exception as e:
        print(f"Error disconnecting all connections: {e}")

def connect_audio_chain_nodes(source: Any, dest: Any):
    """Connect two nodes in the audio chain (plugin IDs or special strings)"""
    if source == "a2j":
        # Connect a2j midi bridge output to plugin input
        if isinstance(dest, int):
            # a2j:midi_* -> plugin:input_*
            plugin_ports = get_plugin_audio_port_count(dest)
            for ch in range(min(2, plugin_ports["inputs"])):
                source_port = f"a2j:midi_{ch + 1}"
                dest_port = get_plugin_jack_port_name(dest, is_output=False, channel=ch)
                if dest_port:
                    time.sleep(0.1)
                    jack_connect(source_port, dest_port)
    elif dest == "system":
        # Connect plugin output to system playback
        if isinstance(source, int):
            plugin_ports = get_plugin_audio_port_count(source)
            for ch in range(min(plugin_ports["outputs"], 2)):
                source_port = get_plugin_jack_port_name(source, is_output=True, channel=ch)
                dest_port = f"system:playback_{ch + 1}"
                if source_port:
                    time.sleep(0.1)
                    jack_connect(source_port, dest_port)
    else:
        # Connect plugin to plugin
        if isinstance(source, int) and isinstance(dest, int):
            source_ports = get_plugin_audio_port_count(source)
            dest_ports = get_plugin_audio_port_count(dest)
            max_channels = min(source_ports["outputs"], dest_ports["inputs"])
            for ch in range(max_channels):
                source_port = get_plugin_jack_port_name(source, is_output=True, channel=ch)
                dest_port = get_plugin_jack_port_name(dest, is_output=False, channel=ch)
                if source_port and dest_port:
                    time.sleep(0.1)
                    jack_connect(source_port, dest_port)

def rebuild_audio_chain():
    """Rebuild all JACK connections from scratch based on AUDIO_CHAIN"""
    print(f"Rebuilding audio chain: {AUDIO_CHAIN}")
    
    # First, disconnect everything
    disconnect_all_audio_connections()
    time.sleep(0.3)
    
    # Then connect everything in order
    for i in range(len(AUDIO_CHAIN) - 1):
        source = AUDIO_CHAIN[i]
        dest = AUDIO_CHAIN[i + 1]
        print(f"Connecting chain[{i}]={source} -> chain[{i+1}]={dest}")
        connect_audio_chain_nodes(source, dest)
        time.sleep(0.2)

def swap_chain_indices(index1: int, index2: int):
    """Swap two plugins in the audio chain and rebuild connections"""
    global AUDIO_CHAIN
    
    # Validate indices (can't swap a2j or system)
    if index1 <= 0 or index1 >= len(AUDIO_CHAIN) - 1:
        raise ValueError(f"Index {index1} is out of bounds (cannot swap a2j or system)")
    if index2 <= 0 or index2 >= len(AUDIO_CHAIN) - 1:
        raise ValueError(f"Index {index2} is out of bounds (cannot swap a2j or system)")
    
    # Swap
    AUDIO_CHAIN[index1], AUDIO_CHAIN[index2] = AUDIO_CHAIN[index2], AUDIO_CHAIN[index1]
    print(f"Swapped indices {index1} and {index2}: {AUDIO_CHAIN}")
    
    # Rebuild all connections
    rebuild_audio_chain()

def _OLD_disconnect_plugin_chain(prev_plugin_id: int, next_plugin_id: int):
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

# Old reroute_plugin_chain function removed - now using rebuild_audio_chain()
def _OLD_reroute_plugin_chain(insert_position: int, new_plugin_id: int):
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

def sync_audio_chain():
    """Sync AUDIO_CHAIN with actual loaded plugins"""
    global AUDIO_CHAIN
    
    count = host.get_current_plugin_count()
    # AUDIO_CHAIN = [a2j, plugin_id1, plugin_id2, ..., system]
    # Keep a2j at start and system at end, update middle plugins
    plugin_ids = list(range(count))
    AUDIO_CHAIN = ["a2j"] + plugin_ids + ["system"]
    
    print(f"Synced audio chain: {AUDIO_CHAIN}")
    # Rebuild connections
    rebuild_audio_chain()


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
sync_audio_chain()

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
    sync_audio_chain()  # Sync chain when listing
    plugins = []
    count = host.get_current_plugin_count()
    for i in range(count):
        info = host.get_plugin_info(i)
        plugins.append({
            "id": i,
            "name": info.get("name", ""),
            "label": info.get("label", ""),
            "chain_position": AUDIO_CHAIN.index(i) if i in AUDIO_CHAIN else -1
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
        
        # Add plugin to audio chain (append before "system")
        # AUDIO_CHAIN = [a2j, plugin_id1, plugin_id2, ..., system]
        # Insert new plugin before "system"
        global AUDIO_CHAIN
        AUDIO_CHAIN.insert(-1, new_plugin_index)  # Insert before last element (system)
        
        # Rebuild all connections
        rebuild_audio_chain()
        
        # Get chain position (excluding a2j and system)
        chain_position = len(AUDIO_CHAIN) - 2  # -2 because we exclude a2j (index 0) and system (last)
        
        return jsonify({
            "status": "ok", 
            "plugin": plugin_info, 
            "plugin_id": new_plugin_index,
            "chain_position": chain_position
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/plugins/chain", methods=["GET"])
def get_plugin_chain():
    """Get the current audio chain order"""
    sync_audio_chain()
    chain_info = []
    for idx, node in enumerate(AUDIO_CHAIN):
        if node == "a2j":
            chain_info.append({
                "position": idx,
                "node": "a2j",
                "name": "a2j MIDI Bridge",
                "label": "MIDI Input"
            })
        elif node == "system":
            chain_info.append({
                "position": idx,
                "node": "system",
                "name": "System Playback",
                "label": "Audio Output"
            })
        else:
            try:
                plugin_info = host.get_plugin_info(node)
                chain_info.append({
                    "position": idx,
                    "plugin_id": node,
                    "name": plugin_info.get("name", ""),
                    "label": plugin_info.get("label", "")
                })
            except:
                continue
    return jsonify({"chain": chain_info})

@app.route("/plugins/move", methods=["POST"])
def move_plugin():
    """Swap two plugins in the audio chain by index"""
    try:
        data = request.get_json(force=True)
        index1 = int(data.get("index1"))
        index2 = int(data.get("index2"))
        
        # Validate indices
        if index1 < 0 or index1 >= len(AUDIO_CHAIN):
            return jsonify({"error": f"Index {index1} is out of bounds"}), 400
        if index2 < 0 or index2 >= len(AUDIO_CHAIN):
            return jsonify({"error": f"Index {index2} is out of bounds"}), 400
        
        # Swap and rebuild
        swap_chain_indices(index1, index2)
        
        return jsonify({
            "status": "ok",
            "index1": index1,
            "index2": index2,
            "chain": AUDIO_CHAIN
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
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
    api_host = api_cfg.get("host", "0.0.0.0")
    api_port = api_cfg.get("port", 8080)
    app.run(host=api_host, port=api_port)
