#!/usr/bin/env python3
"""
Configuration loader for Digital Synthesizer Web App
Loads settings from config.yaml and optional config_local.yaml
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any

# Get the project root directory (where this file is located)
PROJECT_ROOT = Path(__file__).parent.absolute()

# Default config file paths
CONFIG_FILE = PROJECT_ROOT / "config.yaml"
CONFIG_LOCAL_FILE = PROJECT_ROOT / "config_local.yaml"


def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.yaml and optional config_local.yaml
    
    Returns:
        Dictionary containing all configuration settings
    """
    config = {}
    
    # Load main config file
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f) or {}
    else:
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_FILE}\n"
            "Please create config.yaml in the project root."
        )
    
    # Load local overrides if they exist
    if CONFIG_LOCAL_FILE.exists():
        with open(CONFIG_LOCAL_FILE, 'r') as f:
            local_config = yaml.safe_load(f) or {}
            # Merge local config over main config
            config = _deep_merge(config, local_config)
    
    return config


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries, with override taking precedence"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Global config instance (loaded on import)
_config = None


def get_config() -> Dict[str, Any]:
    """Get the global configuration (lazy-loaded)"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


# Convenience functions for common config values
def get_carla_config() -> Dict[str, Any]:
    """Get Carla configuration"""
    return get_config().get("carla", {})


def get_osc_config() -> Dict[str, Any]:
    """Get OSC configuration"""
    return get_config().get("osc", {})


def get_flask_config() -> Dict[str, Any]:
    """Get Flask configuration"""
    return get_config().get("flask", {})


def get_carla_api_config() -> Dict[str, Any]:
    """Get Carla API configuration"""
    return get_config().get("carla_api", {})

