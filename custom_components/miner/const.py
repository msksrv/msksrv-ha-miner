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
CONF_ENERGY_SOURCE_MODE = "energy_source_mode"
CONF_ENERGY_PHYSICAL_SENSOR = "energy_physical_sensor"
CONF_ENERGY_POWER_SENSOR = "energy_power_sensor"
CONF_FARM_ENERGY_PHYSICAL_SENSOR = "farm_energy_physical_sensor"
CONF_FARM_LEGACY_COST_SENSORS = "farm_legacy_cost_sensors_enabled"
CONF_HEALTH_PROFILE = "health_profile"
CONF_HEALTH_THRESHOLDS = "health_thresholds"
CONF_REPAIR_CONFIRM_DEFAULT = "repair_confirm_default_seconds"
CONF_REPAIR_RECOVERY = "repair_recovery_seconds"
CONF_REPAIR_CONFIRM_OVERRIDES = "repair_confirm_overrides"
CONF_AUTO_RECOVERY_ENABLED = "auto_recovery_enabled"
CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS = "auto_recovery_pre_action_seconds"
CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS = "auto_recovery_post_reboot_seconds"
CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS = "auto_recovery_post_power_on_seconds"
CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED = "auto_recovery_power_cycle_enabled"
CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS = "auto_recovery_power_off_pause_seconds"
CONF_AUTO_RECOVERY_MAX_REBOOTS = "auto_recovery_max_reboots"
CONF_AUTO_RECOVERY_MAX_POWER_CYCLES = "auto_recovery_max_power_cycles"
CONF_AUTO_RECOVERY_COOLDOWN_SECONDS = "auto_recovery_cooldown_seconds"
CONF_AUTO_RECOVERY_CONFIG_BLOCK_SECONDS = "auto_recovery_config_block_seconds"
CONF_IS_FARM = "is_farm"
CONF_FARM_DEVICE_IDS = "farm_device_ids"
CONF_FARM_AMBIENT_TEMP_ENTITIES = "farm_ambient_temp_entities"
CONF_FARM_ENERGY_RATES = "farm_energy_rates"
CONF_FARM_ELEC_TARIFF_MODE = "farm_elec_tariff_mode"
CONF_FARM_ELEC_TOU_CURRENCY = "farm_elec_tou_currency"
CONF_FARM_ELEC_ZONES = "farm_elec_zones"

ENERGY_SOURCE_AUTO = "auto"
ENERGY_SOURCE_PHYSICAL = "physical"
ENERGY_SOURCE_SWITCH_POWER = "switch_power"
ENERGY_SOURCE_MINER_POWER = "miner_power"

FARM_ELEC_TARIFF_FLAT = "flat"
FARM_ELEC_TARIFF_DUAL = "dual"
FARM_ELEC_TARIFF_TRIPLE = "triple"
CONF_FARM_POOL_PRESETS = "farm_pool_presets"
CONF_FARM_POOL_HOST = "farm_pool_host"
CONF_FARM_POOL_PORT = "farm_pool_port"
CONF_FARM_POOL_USE_SSL = "farm_pool_use_ssl"
CONF_FARM_POOL_USERNAME = "farm_pool_username"
CONF_FARM_POOL_PASSWORD = "farm_pool_password"

SERVICE_REBOOT = "reboot"
SERVICE_RESTART_BACKEND = "restart_backend"
SERVICE_SET_WORK_MODE = "set_work_mode"
SERVICE_SET_POOL = "set_pool"
SERVICE_SET_FARM_POOL = "set_farm_pool"

TERA_HASH_PER_SECOND = "TH/s"
JOULES_PER_TERA_HASH = "J/TH"

DEFAULT_MIN_POWER = 15
DEFAULT_MAX_POWER = 10000
DEFAULT_SUBNET = "192.168.1.0/24"

HEALTH_PROFILE_AUTO = "auto"
HEALTH_PROFILE_GENERIC = "generic"
HEALTH_PROFILE_CUSTOM = "custom"

HEALTH_PROFILE_OPTIONS: tuple[str, ...] = (
    HEALTH_PROFILE_AUTO,
    HEALTH_PROFILE_GENERIC,
    HEALTH_PROFILE_CUSTOM,
)

SCAN_PORTS: tuple[int, ...] = (4028, 80, 443)
SCAN_TCP_TIMEOUT = 0.35
SCAN_MINER_TIMEOUT = 2.5
SCAN_CONCURRENCY = 20
SCAN_MAX_HOSTS = 1024