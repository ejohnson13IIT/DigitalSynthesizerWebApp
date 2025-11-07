#!/usr/bin/env python3
"""
Monitor the first parameter of the first plugin in Carla.
Prints the parameter value every 2 seconds.
"""

import requests
import time
import sys
import os
from datetime import datetime

# Add project root to path for config loader
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_loader import get_carla_api_config

# Load Carla API configuration
api_cfg = get_carla_api_config()
api_host = api_cfg.get("host", "0.0.0.0")
api_port = api_cfg.get("port", 8080)

# Use localhost for API access (even if host is 0.0.0.0)
BASE_URL = f"http://127.0.0.1:{api_port}"

def get_parameter_value(plugin_id=0, parameter_id=0):
    """Get the value of a specific parameter from a plugin."""
    try:
        # Get all parameters for the plugin
        response = requests.get(f"{BASE_URL}/plugins/{plugin_id}/parameters", timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            parameters = data.get("parameters", [])
            
            if parameter_id < len(parameters):
                param = parameters[parameter_id]
                return {
                    "value": param.get("value"),
                    "name": param.get("name", f"Parameter {parameter_id}"),
                    "min": param.get("min", 0.0),
                    "max": param.get("max", 1.0)
                }
            else:
                return None
        else:
            print(f"Error: API returned status {response.status_code}")
            return None
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to Carla API at {BASE_URL}")
        print("Make sure carla_startup.py is running!")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    """Main monitoring loop."""
    print("=" * 60)
    print("Carla Parameter Monitor")
    print("=" * 60)
    print(f"Monitoring: Plugin 0, Parameter 0")
    print(f"API URL: {BASE_URL}")
    print(f"Update interval: 2 seconds")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    try:
        while True:
            # Get the parameter value
            param_info = get_parameter_value(plugin_id=0, parameter_id=0)
            
            if param_info:
                timestamp = datetime.now().strftime("%H:%M:%S")
                value = param_info["value"]
                name = param_info["name"]
                min_val = param_info["min"]
                max_val = param_info["max"]
                
                # Calculate percentage if min/max are valid
                if max_val != min_val:
                    percentage = ((value - min_val) / (max_val - min_val)) * 100
                    print(f"[{timestamp}] {name}: {value:.4f} ({percentage:.1f}%) [range: {min_val:.2f} - {max_val:.2f}]")
                else:
                    print(f"[{timestamp}] {name}: {value:.4f} [range: {min_val:.2f} - {max_val:.2f}]")
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] Error: Could not retrieve parameter value")
            
            # Wait 2 seconds before next update
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()

