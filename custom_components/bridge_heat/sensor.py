from homeassistant.helpers.entity import Entity

from .const import DOMAIN

# Function to read the status of the integration
async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BridgeHeatSensor(hass, entry)])


class BridgeHeatSensor(Entity):
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry

        self._attr_name = "Bridge Heat"
        self._attr_unique_id = "bridge_heat"

    @property
    def state(self):
        data = self.hass.data[DOMAIN][self.entry.entry_id]
        return data.get("status", "Unknown")

    @property
    def extra_state_attributes(self):
        data = self.hass.data[DOMAIN][self.entry.entry_id]

        return {
            "samples": len(data.get("samples", [])),
            "last_upload": data.get("last_upload"),
            "last_error": data.get("last_error"),
        }

    @property
    def should_poll(self):
        return False
