from homeassistant.helpers import selector
from homeassistant import config_entries
import voluptuous as vol
from .const import *

# Setting up User Permissions, modify as needed
PERMS_SCHEMA = vol.Schema({
    vol.Optional(TEMP, default=False): bool,
    vol.Optional(HUMIDITY, default=False): bool,
    vol.Optional(PRESSURE, default=False): bool,
    vol.Optional(LIGHT, default=False): bool,
    vol.Optional(HVAC, default=False): bool,
    vol.Optional(ENERGY, default=False): bool,
    vol.Optional(NOISE, default=False): bool,
    vol.Optional(AQ, default=False): bool,
    #add more permissions here
})

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=PERMS_SCHEMA,
            )

        return self.async_create_entry(
            title=PERMS_TITLE,
            data = {},
            options=user_input,
        )
    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler()

class OptionsFlowHandler(config_entries.OptionsFlow):

    async def async_step_init(self, user_input=None):
        return await self.async_step_options()

# Modify this function to change the environmental variables needed

    async def async_step_options(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="options",
                data_schema=vol.Schema({
                    vol.Optional(
                        TEMP,
                        default=self.config_entry.options.get(TEMP, False),
                    ): bool,
                    vol.Optional(
                        HUMIDITY,
                        default=self.config_entry.options.get(HUMIDITY, False),
                    ): bool,
                    vol.Optional(
                        PRESSURE,
                        default=self.config_entry.options.get(PRESSURE, False),
                    ): bool,
                    vol.Optional(
                        LIGHT,
                        default=self.config_entry.options.get(LIGHT, False),
                    ): bool,
                    vol.Optional(
                        HVAC,
                        default=self.config_entry.options.get(HVAC, False),
                    ): bool,
                    vol.Optional(
                        ENERGY,
                        default=self.config_entry.options.get(ENERGY, False),
                    ): bool,
                    vol.Optional(
                        NOISE,
                        default=self.config_entry.options.get(NOISE, False),
                    ): bool,
                    vol.Optional(
                        AQ,
                        default = self.config_entry.options.get(AQ, False),
                    ): bool,
                    #add more permissions here
                }),
            )

        return self.async_create_entry(
            title="",
            data=user_input,
        )


