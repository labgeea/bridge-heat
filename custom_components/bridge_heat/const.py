DOMAIN = "bridge_heat"
PLATFORMS = ["sensor"]

# Periodic scheduled upload interval (in seconds)
# Production default: 24 hours (60 * 24 * 60 = 86400 seconds)
UPLOAD_INTERVAL = 60 * 24 * 60
SAMPLE_INTERVAL = 60 * 24 * 60

# Periodic poll interval for checking pending on-demand upload requests from remote server (in seconds)
# Kept at 60 seconds (1 minute) for responsive remote test uploads
POLL_INTERVAL = 60

# Point to remote testing server (change to production server https://bridgeheat.mssm.edu/api/v1 when ready)
API_BASE_URL = "http://142.93.68.156:8080/api/v1"
URL = f"{API_BASE_URL}/env"
PENDING_UPLOADS_URL = f"{API_BASE_URL}/pending-uploads"
ACKNOWLEDGE_URL = f"{API_BASE_URL}/acknowledge-upload"
KEY = "sb_secret_4jlAjWFgrbVh44Y_nkOvYw_Wj5D_gfU"

TEMP = "Temperature"
HUMIDITY = "Humidity"
PRESSURE = "Pressure"
AQ = "Air Quality"
PERMS_TITLE = "Permissions"

# Broadened sensor name wildcards to match environmental sensors across hardware brands
# e.g. Aqara: sensor.lumi_lumi_weather_temperature
#      Hue:   sensor.office_hue_temperature_temperature
#      Sonoff: sensor.snzb_02_temperature
TEMP_ATTR = {
    "name": "sensor.%temp%",
    "device_class": "temperature",
    "units_of_measurement": ["°C", "°F", "C", "F", "K"],
}
PRESSURE_ATTR = {
    "name": "sensor.%press%",
    "device_class": "pressure",
    "units_of_measurement": ["psi", "Pa", "kPa", "hPa", "mmHg", "inHg", "bar", "mbar"],
}
HUMIDITY_ATTR = {
    "name": "sensor.%hum%",
    "device_class": "humidity",
    "units_of_measurement": ["%"],
}
AQ_ATTR = {
    "name": "sensor.%air_quality%",
    "device_class": "aqi",
    "units_of_measurement": ["AQI"],
}
