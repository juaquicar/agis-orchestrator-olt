import os
import yaml

CONFIG_PATH = os.getenv("OLT_CONFIG_PATH", "/config/olts.yaml")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        raw = yaml.safe_load(f)

    defaults = raw.get("defaults", {})
    for olt in raw.get("olts", []):
        for k, v in defaults.items():
            olt.setdefault(k, v)
    return raw.get("olts", [])


# Normalización de estados a enteros
# unknown = 98
# pending = 99
STATUS_NORMALIZE = {
    # Zyxel 1408A/2406: típicamente "IS"/"NOT" en tabla
    "zyxel1408A": {
        "NOT": 0,
        "IS": 1,
        "OOS": 0,
        "DOWN": 0,
        "UP": 1,
        "OOS-DG": 3,  # Sin energía
        "OOS-LS": 2,  # Lossi
        "OOS-NR": 1,  # NO REGISTRADA
        "OOS-PF": 0,  # Provision fail
        "OOS-CD": 0,  # Omci CAIDO
        "OOS-NP": 1,  # No tiene servicios asignados
        "OOS-SB": 1,  # StandBy
        "O7": 1,  # Prohibida
    },
    "zyxel2406": {
        "NOT": 0,
        "IS": 1, # Active
        "OOS": 0,
        "DOWN": 0,
        "UP": 1,
        "OOS-DG": 3, # Sin energía
        "OOS-LS": 2, # Lossi
        "OOS-NR": 1, # NO REGISTRADA
        "OOS-PF": 0, # Provision fail
        "OOS-CD": 0, # Omci CAIDO
        "OOS-NP": 1, # No tiene servicios asignados
        "OOS-SB": 1, # StandBy
        "O7": 1, # Prohibida
    },

    # Zyxel 1240XA: en outputs reales aparece "Active" (y variantes)
    "zyxel1240XA": {
        "ACTIVE": 1,
        "INACTIVE": 0,
        "UP": 1,
        "DOWN": 0,
        "IS": 1,
        "NOT": 0,
        "OOS": 0,
        "OOS-DG": 3,  # Sin energía
        "OOS-LS": 2,  # Lossi
        "OOS-NR": 1,  # NO REGISTRADA
        "OOS-PF": 0,  # Provision fail
        "OOS-CD": 0,  # Omci CAIDO
        "OOS-NP": 1,  # No tiene servicios asignados
        "OOS-SB": 1,  # StandBy
        "O7": 1,  # Prohibida
    },

    "huawei": {
        "offline": 0,
        "online": 1,
        "losi": 2,
        "dyinggasp": 3,
    },
}
