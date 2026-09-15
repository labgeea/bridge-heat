DOMAIN = "bridge_heat"
PLATFORMS = ["sensor"]

# Periodic scheduled upload interval (in seconds)
# Set to 5 minutes for immediate testing (default production: 60 * 24 * 60)
UPLOAD_INTERVAL = 60 * 5
SAMPLE_INTERVAL = 60 * 24 * 60

# Periodic poll interval for checking pending on-demand upload requests (in seconds)
# Default is 60 seconds (1 minute), can be configured as needed
POLL_INTERVAL = 60

# Point to local Mac Laravel server for testing (change to production server when deploying)
API_BASE_URL = "http://192.168.1.39:9003/api/v1"
URL = f"{API_BASE_URL}/env"
PENDING_UPLOADS_URL = f"{API_BASE_URL}/pending-uploads"
ACKNOWLEDGE_URL = f"{API_BASE_URL}/acknowledge-upload"
KEY = "sb_secret_4jlAjWFgrbVh44Y_nkOvYw_Wj5D_gfU"

TEMP = "Temperature"
HUMIDITY = "Humidity"
PRESSURE = "Pressure"
LIGHT = "Light"
HVAC = "HVAC"
ENERGY = "Energy"
NOISE = "Noise"
AQ = "Air Quality"
PERMS_TITLE = "Permissions"
TEMP_ATTR = {"name" : "sensor.%temperature%", "device_class" : 'temperature', "units_of_measurement" : ["°C", "°F", "K"]}
PRESSURE_ATTR = {"name" : "sensor.%pressure%", "device_class" : 'pressure', "units_of_measurement" : ["psi", "Pa", "kPa", "hPa", "mmHg", "bar", "mbar"]}
HUMIDITY_ATTR = {"name" : "sensor.%humidity%", "device_class" : 'humidity'}
LIGHT_ATTR = {"name" : "light.%"}
HVAC_ATTR = {"name" : "climate.%"}
ENERGY_ATTR = {"name" : "sensor.%energy%", "device_class" : "energy", "units_of_measurement": ["Wh", "kWh", "MWh"]}
NOISE_ATTR = {"name" : "sensor.%noise%", "device_class" : "sound_pressure", "units_of_measurement" : ["dB", "dBA"]}
AQ_ATTR = {
    "name": "sensor.%air_quality%",
    "device_class": "aqi",
    "units_of_measurement": ["AQI"]
}

