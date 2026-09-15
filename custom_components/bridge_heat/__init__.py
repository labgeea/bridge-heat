import json
import asyncio
from datetime import datetime, timedelta, time

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .uploader import send_data, check_pending_uploads, acknowledge_upload

import logging
import sqlite3

import random

from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers import instance_id
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

_LOGGER.info("Integration loaded")


async def get_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Retrieve the permanent unique Home Assistant instance UUID."""
    try:
        uuid = await instance_id.async_get(hass)
        if uuid:
            return str(uuid)
    except Exception as err:
        _LOGGER.debug("Could not retrieve instance_id: %s", err)

    return str(entry.entry_id)

async def async_setup(hass: HomeAssistant, config):
    hass.data.setdefault(DOMAIN, {})
    return True

async def fetch_data(hass: HomeAssistant, entry: ConfigEntry):
    def query_db():
        dicts = []
        # checking user permissions for each environmental variable, modify as needed
        if entry.options.get(TEMP):
            dicts.append(TEMP_ATTR)
        if entry.options.get(PRESSURE):
            dicts.append(PRESSURE_ATTR)
        if entry.options.get(HUMIDITY):
            dicts.append(HUMIDITY_ATTR)
        if entry.options.get(AQ):
            dicts.append(AQ_ATTR)
        if entry.options.get(ENERGY):
            dicts.append(ENERGY_ATTR)
        if entry.options.get(HVAC):
            dicts.append(HVAC_ATTR)
        if entry.options.get(LIGHT):
            dicts.append(LIGHT_ATTR)
        if entry.options.get(NOISE):
            dicts.append(NOISE_ATTR)
        
        DICT = {}
        for d in dicts:
            for k, v in d.items():
                DICT.setdefault(k, []).append(v)
        # connecting to the database and setting up the query
        db_path = hass.config.path("home-assistant_v2.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        CLAUSE = " OR ".join([f"m.entity_id LIKE ?" for _ in DICT['name']])
        names = [DICT['name']]
        device_class = [DICT['device_class']]
        units = list(DICT['units_of_measurement'])
        params_prelim = names + device_class + units + [[SAMPLE_INTERVAL]]
        params = [item for sublist in params_prelim for item in sublist]
        # Query: join states and metadata, filter sensors by unit in attributes
        query = f"""SELECT s.state, s.metadata_id, m.entity_id, a.shared_attrs, s.last_updated_ts
                FROM states s
                JOIN states_meta m 
                ON s.metadata_id = m.metadata_id
                JOIN state_attributes a
                ON s.attributes_id = a.attributes_id
                WHERE (
                    {CLAUSE}
                    OR json_extract(a.shared_attrs, '$.device_class') IN ({','.join(['?'] * len(DICT['device_class']))})
                    OR json_extract(a.shared_attrs, '$.unit_of_measurement') IN ({','.join(['?'] * sum(len(sublist) for sublist in DICT['units_of_measurement']))})
                )
                AND s.last_updated_ts >= strftime('%s','now') - ?
                ORDER BY s.metadata_id, s.last_updated_ts;"""
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        latitude = hass.config.latitude
        longitude = hass.config.longitude

        location = str(latitude) + ', ' + str(longitude)

        results = []
        for r in rows:
            try:
                attrs = json.loads(r["shared_attrs"])
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            state = str(r["state"])
            results.append({
                "location": location,
                "entity": r["entity_id"],
                "attributes": attrs,
                "state": state,
                "time": datetime.utcfromtimestamp(r["last_updated_ts"]).strftime("%Y-%m-%d %H:%M:%S")
            })
            with open("debug.txt", "w") as f:
                f.write(f"{results}\n")
        return results

    # Run blocking SQLite query in a separate thread for asynchronous function
    return await hass.async_add_executor_job(query_db)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    device_id = await get_device_id(hass, entry)
    _LOGGER.info("Bridge Heat called (device_id: %s)", device_id)

    hass.data[DOMAIN][entry.entry_id] = {
        "device_id": device_id,
        "samples": [],
        "status": "Waiting for first upload",
        "last_upload": None,
        "last_error": None,
    }

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    async def upload_job(now):
        samples = await fetch_data(hass, entry)
        hass.data[DOMAIN][entry.entry_id]["samples"] = samples

        if not samples:
            _LOGGER.info("No Samples to Upload")
            return

        latitude = hass.config.latitude
        longitude = hass.config.longitude
        location = f"{latitude}, {longitude}"

        try:
            hass.data[DOMAIN][entry.entry_id]["status"] = "Uploading"
            await send_data(samples, location=location, device_id=device_id)

            hass.data[DOMAIN][entry.entry_id]["samples"] = []
            hass.data[DOMAIN][entry.entry_id]["status"] = "Idle"
            hass.data[DOMAIN][entry.entry_id]["last_upload"] = dt_util.utcnow().isoformat()
            hass.data[DOMAIN][entry.entry_id]["last_error"] = None

            _LOGGER.info("Upload successful (device_id: %s)", device_id)

        except Exception as err:
            hass.data[DOMAIN][entry.entry_id]["status"] = "Upload failed"
            hass.data[DOMAIN][entry.entry_id]["last_error"] = str(err)

            _LOGGER.error("Upload failed: %s", err)

    async def start_periodic_upload(now):
        _LOGGER.info("Starting periodic uploads")

        remove_upload = async_track_time_interval(
            hass,
            upload_job,
            timedelta(seconds = UPLOAD_INTERVAL),
        )

        hass.data[DOMAIN][entry.entry_id]["remove_upload"] = remove_upload

        await upload_job(now)

    async def poll_pending_requests(now):
        latitude = hass.config.latitude
        longitude = hass.config.longitude
        location = f"{latitude}, {longitude}"

        try:
            pending = await check_pending_uploads(device_id=device_id, location=location)
            if not pending:
                return

            for req in pending:
                req_id = req.get("id")
                _LOGGER.info("Processing pending upload request #%s for location %s", req_id, location)
                await acknowledge_upload(req_id, "acknowledged")

                try:
                    await upload_job(now)
                    await acknowledge_upload(
                        req_id,
                        "completed",
                        notes="Uploaded data successfully via on-demand trigger."
                    )
                except Exception as err:
                    _LOGGER.error("On-demand upload execution failed for request #%s: %s", req_id, err)
                    await acknowledge_upload(
                        req_id,
                        "failed",
                        notes=f"Execution error: {err}"
                    )
        except Exception as err:
            _LOGGER.debug("Error during pending upload check: %s", err)

    # Start periodic polling for pending on-demand upload requests
    _LOGGER.info("Starting on-demand upload polling every %ss", POLL_INTERVAL)
    remove_poll = async_track_time_interval(
        hass,
        poll_pending_requests,
        timedelta(seconds=POLL_INTERVAL),
    )
    hass.data[DOMAIN][entry.entry_id]["remove_poll"] = remove_poll

    # For testing or short intervals (<= 15 minutes), start first upload after 60 seconds
    if UPLOAD_INTERVAL <= 900:
        delay = 60
        _LOGGER.info("Testing/short interval detected (%ss). First upload in %ss.", UPLOAD_INTERVAL, delay)
    else:
        # Pick random time between 12 AM and 6 AM
        now_local = dt_util.now()
        random_hour = random.randint(0, 5)
        random_minute = random.randint(0, 59)

        target_time = datetime.combine(
            now_local.date(),
            time(random_hour, random_minute),
            tzinfo=now_local.tzinfo,
        )

        # If today's random time already passed, use tomorrow
        if target_time <= now_local:
            target_time += timedelta(days=1)

        delay = (target_time - now_local).total_seconds()

        _LOGGER.info(
            "First upload scheduled for %s",
            target_time.isoformat(),
        )

    remove_start = async_call_later(
        hass,
        delay,
        start_periodic_upload,
    )

    hass.data[DOMAIN][entry.entry_id]["remove_start"] = remove_start

    return True


async def async_unload_entry(hass, entry):
    data = hass.data[DOMAIN].pop(entry.entry_id)

    if data.get("remove_upload"):
        data["remove_upload"]()

    if data.get("remove_start"):
        data["remove_start"]()

    if data.get("remove_poll"):
        data["remove_poll"]()

    return True
