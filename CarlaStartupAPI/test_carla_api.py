import requests
import json

BASE_URL = "http://localhost:8080"

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
    test_endpoint("/plugins")                # List all plugins
    test_endpoint("/plugins/1/parameters")   # List parameters for plugin 0
