import requests
import json
import sys
import os

# Add project root to path for config loader
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import get_carla_api_config

# Load Carla API configuration
api_cfg = get_carla_api_config()
api_host = api_cfg.get("host", "0.0.0.0")
api_port = api_cfg.get("port", 8080)

# Use localhost for testing (even if host is 0.0.0.0)
BASE_URL = f"http://127.0.0.1:{api_port}"

def test_endpoint(path):
    try:
        res = requests.get(BASE_URL + path)
        print(f"GET {path} -> {res.status_code}")
        if res.ok:
            print(json.dumps(res.json(), indent=2))
        else:
            print(res.text)
    except Exception as e:
        print(f"Error contacting {path}: {e}")

if __name__ == "__main__":
    print("=== Testing Carla API ===\n")
    print(f"Testing API at {BASE_URL}\n")
    test_endpoint("/plugins")                # List all plugins
    test_endpoint("/plugins/0/parameters")   # List parameters for plugin 0 (first plugin)
