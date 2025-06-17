import os, yaml, pathlib

CONFIG_PATH = os.getenv("OLT_CONFIG_PATH", "/config/olts.yaml")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        raw = yaml.safe_load(f)
    defaults = raw.get("defaults", {})
    for olt in raw["olts"]:
        for k, v in defaults.items():
            olt.setdefault(k, v)
    return raw["olts"]
