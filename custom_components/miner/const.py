"""Constants for the Miner integration."""

DOMAIN = "miner"

CONF_IP = "ip"
CONF_TITLE = "title"
CONF_SSH_PASSWORD = "ssh_password"
CONF_SSH_USERNAME = "ssh_username"
CONF_RPC_PASSWORD = "rpc_password"
CONF_WEB_PASSWORD = "web_password"
CONF_WEB_USERNAME = "web_username"
CONF_MIN_POWER = "min_power"
CONF_MAX_POWER = "max_power"
CONF_SUBNET = "subnet"
CONF_SELECTED_MINER = "selected_miner"
CONF_POWER_SWITCH = "power_switch"
CONF_IS_FARM = "is_farm"
CONF_FARM_DEVICE_IDS = "farm_device_ids"

SERVICE_REBOOT = "reboot"
SERVICE_RESTART_BACKEND = "restart_backend"
SERVICE_SET_WORK_MODE = "set_work_mode"
SERVICE_SET_POOL = "set_pool"

TERA_HASH_PER_SECOND = "TH/s"
JOULES_PER_TERA_HASH = "J/TH"

DEFAULT_MIN_POWER = 15
DEFAULT_MAX_POWER = 10000
DEFAULT_SUBNET = "192.168.1.0/24"

SCAN_PORTS: tuple[int, ...] = (4028, 80, 443)
SCAN_TCP_TIMEOUT = 0.35
SCAN_MINER_TIMEOUT = 2.5
SCAN_CONCURRENCY = 20
SCAN_MAX_HOSTS = 1024