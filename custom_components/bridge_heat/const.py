DOMAIN = "bridge_heat"
PLATFORMS = ["sensor"]

# Periodic scheduled upload interval (in seconds)
# Production default: 24 hours (60 * 24 * 60 = 86400 seconds)
UPLOAD_INTERVAL = 60 * 24 * 60
SAMPLE_INTERVAL = 60 * 24 * 60

# Periodic poll interval for checking pending on-demand upload requests from production server (in seconds)
# Kept at 60 seconds (1 minute) for responsive remote on-demand uploads
POLL_INTERVAL = 60

# Official Production Server
API_BASE_URL = "https://bridgeheat.mssm.edu/api/v1"
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
