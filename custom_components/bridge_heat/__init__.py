import json
import asyncio
import uuid as uuid_lib
import fnmatch
import logging
import random
import sqlite3
from datetime import datetime, timedelta, time

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers import instance_id
from homeassistant.util import dt as dt_util

from .const import *
from .uploader import send_data, check_pending_uploads, acknowledge_upload

_LOGGER = logging.getLogger(__name__)

_LOGGER.info("Bridge Heat Integration loaded")

# Keywords that indicate non-environmental sensors (batteries, CPU, memory, power, backups, etc.)
EXCLUDED_KEYWORDS = (
    "battery", "cpu", "processor", "memory", "disk", "swap", "load",
    "storage", "ram", "gpu", "voltage", "current", "power", "signal",
    "rssi", "linkquality", "illuminance", "energy", "consumption",
    "uptime", "ping", "latency", "brightness", "speed", "volume",
    "valve", "co2", "voc", "backup", "attempt", "timestamp"
)

TEMP_UNITS = {"°c", "°f", "c", "f", "k"}
PRESSURE_UNITS = {"psi", "pa", "kpa", "hpa", "mmhg", "inhg", "bar", "mbar"}


def is_environmental_sensor(entity_id: str, attributes: dict, include_aq: bool = False) -> bool:
    """Strictly verify whether an entity is an environmental sensor."""
    ent = entity_id.lower()

    # Must be a sensor
    if not ent.startswith("sensor."):
        return False

    # Exclude system, backup, diagnostic, and battery sensors
    for kw in EXCLUDED_KEYWORDS:
        if kw in ent:
            return False

    dc = str(attributes.get("device_class") or "").lower()
    unit = str(attributes.get("unit_of_measurement") or "").strip().lower()

    # Temperature (matches device_class temperature, or explicit _temp/temperature word with temperature unit)
    if dc == "temperature" or (any(term in ent for term in ("_temp", ".temp", "temperature")) and unit in TEMP_UNITS):
        return True

    # Humidity (matches device_class humidity, or explicit _hum/humidity word with % unit)
    if dc == "humidity" or (any(term in ent for term in ("_hum", ".hum", "humidity")) and unit == "%"):
        return True

    # Pressure
    if dc == "pressure" or (any(term in ent for term in ("_press", ".press", "pressure", "barometer")) and unit in PRESSURE_UNITS):
        return True

    # Air Quality (optional)
    if include_aq and (dc == "aqi" or "aqi" in ent or "air_quality" in ent):
        return True

    return False


async def get_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Generate a unique device ID from the hardware MAC address.

    Even if the HA image/backup is cloned across multiple devices,
    each physical device has a unique MAC address burned into its
    network interface, guaranteeing a distinct device_id.
    """
    try:
        mac = uuid_lib.getnode()
        # getnode() returns a 48-bit integer; format as 12-char hex
        mac_hex = f"{mac:012x}"
        device_id = f"ha-{mac_hex}"
        _LOGGER.debug("Using hardware MAC-based device_id: %s", device_id)
        return device_id
    except Exception as err:
        _LOGGER.warning("Could not read hardware MAC: %s, falling back to instance_id", err)

    # Fallback to HA instance UUID if MAC is unavailable
    try:
        ha_uuid = await instance_id.async_get(hass)
        if ha_uuid:
            return str(ha_uuid)
    except Exception as err:
        _LOGGER.debug("Could not retrieve instance_id: %s", err)

    return str(entry.entry_id)


async def async_setup(hass: HomeAssistant, config):
    hass.data.setdefault(DOMAIN, {})

    async def handle_trigger_upload(call):
        """Service to trigger data upload immediately (e.g. for testing)."""
        _LOGGER.info("Manual upload triggered via service call")
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if isinstance(entry_data, dict) and "upload_job" in entry_data:
                await entry_data["upload_job"](None, force_sample_window=SAMPLE_INTERVAL)

    hass.services.async_register(DOMAIN, "upload_data", handle_trigger_upload)
    return True


async def fetch_data(hass: HomeAssistant, entry: ConfigEntry, force_sample_window: int = None):
    include_aq = entry.options.get(AQ, False)
    last_upload_ts = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("last_upload_ts")

    # Fast in-memory resolution: identify actual environmental sensors currently active in HA
    matched_entity_ids = set()
    for state in hass.states.async_all():
        if is_environmental_sensor(state.entity_id, state.attributes, include_aq=include_aq):
            matched_entity_ids.add(state.entity_id)

    _LOGGER.info("Identified %d environmental sensors in memory: %s", len(matched_entity_ids), list(matched_entity_ids))

    def query_db():
        # Open SQLite in URI read-only mode to prevent write-lock contention with HA Recorder
        db_path = hass.config.path("home-assistant_v2.db")
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        metadata_map = {}

        # 1. Map in-memory identified entities to metadata_id
        if matched_entity_ids:
            chunk_size = 500
            ent_list = list(matched_entity_ids)
            for i in range(0, len(ent_list), chunk_size):
                chunk = ent_list[i:i + chunk_size]
                placeholders = ",".join(["?" for _ in chunk])
                cur.execute(f"SELECT metadata_id, entity_id FROM states_meta WHERE entity_id IN ({placeholders})", chunk)
                for r in cur.fetchall():
                    metadata_map[r["metadata_id"]] = r["entity_id"]

        # 2. Search states_meta with precise patterns (excluding backup/attempt/battery/system)
        exclude_clauses = " AND ".join([f"LOWER(entity_id) NOT LIKE '%{kw}%'" for kw in EXCLUDED_KEYWORDS])
        cur.execute(f"""
            SELECT metadata_id, entity_id FROM states_meta
            WHERE (entity_id LIKE 'sensor.%temperature%' OR entity_id LIKE 'sensor.%_temp%' 
                OR entity_id LIKE 'sensor.%humidity%' OR entity_id LIKE 'sensor.%_hum%' 
                OR entity_id LIKE 'sensor.%pressure%' OR entity_id LIKE 'sensor.%_press%')
              AND {exclude_clauses}
        """)
        for r in cur.fetchall():
            metadata_map[r["metadata_id"]] = r["entity_id"]

        if not metadata_map:
            conn.close()
            _LOGGER.warning("No matching environmental sensor metadata found in states_meta table!")
            return []

        # Determine reference timestamp from SQLite itself to guarantee perfect time sync
        cur.execute("SELECT strftime('%s', 'now');")
        db_now_row = cur.fetchone()
        db_now = int(db_now_row[0]) if db_now_row and db_now_row[0] else int(dt_util.utcnow().timestamp())

        if force_sample_window is not None:
            since_ts = db_now - force_sample_window
        elif last_upload_ts and last_upload_ts > 0:
            since_ts = max(int(last_upload_ts), db_now - SAMPLE_INTERVAL)
        else:
            since_ts = db_now - SAMPLE_INTERVAL

        _LOGGER.info("Querying database for %d sensors since timestamp %s (current DB time: %s)", len(metadata_map), since_ts, db_now)

        # Query states using the composite index (metadata_id, last_updated_ts)
        meta_ids = list(metadata_map.keys())
        meta_placeholders = ",".join(["?" for _ in meta_ids])

        query = f"""SELECT s.state, s.metadata_id, a.shared_attrs, s.last_updated_ts
                FROM states s
                LEFT JOIN state_attributes a
                ON s.attributes_id = a.attributes_id
                WHERE s.metadata_id IN ({meta_placeholders})
                  AND s.state NOT IN ('unknown', 'unavailable', '')
                  AND s.last_updated_ts >= ?
                ORDER BY s.metadata_id, s.last_updated_ts;"""

        params = meta_ids + [since_ts]
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()

        _LOGGER.info("Indexed query returned %d rows for %d sensors", len(rows), len(meta_ids))

        latitude = hass.config.latitude
        longitude = hass.config.longitude
        location = f"{latitude}, {longitude}"

        results = []
        for r in rows:
            attrs = {}
            if r["shared_attrs"]:
                try:
                    attrs = json.loads(r["shared_attrs"])
                except (ValueError, TypeError, json.JSONDecodeError):
                    attrs = {}
            entity_id = metadata_map.get(r["metadata_id"], "unknown")

            # Final validation check: strictly verify entity is a genuine environmental sensor
            if not is_environmental_sensor(entity_id, attrs, include_aq=include_aq):
                continue

            state = str(r["state"])
            results.append({
                "location": location,
                "entity": entity_id,
                "attributes": attrs,
                "state": state,
                "time": datetime.utcfromtimestamp(r["last_updated_ts"]).strftime("%Y-%m-%d %H:%M:%S")
            })
        return results

    return await hass.async_add_executor_job(query_db)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    device_id = await get_device_id(hass, entry)
    _LOGGER.info("Bridge Heat called (device_id: %s)", device_id)

    hass.data[DOMAIN][entry.entry_id] = {
        "device_id": device_id,
        "samples": [],
        "status": "Waiting for first upload",
        "last_upload": None,
        "last_upload_ts": None,
        "last_error": None,
    }

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    async def upload_job(now, force_sample_window: int = None):
        samples = await fetch_data(hass, entry, force_sample_window=force_sample_window)
        hass.data[DOMAIN][entry.entry_id]["samples"] = samples

        if not samples:
            _LOGGER.warning("No samples found to upload for device %s", device_id)
            if hass.data[DOMAIN][entry.entry_id]["status"] != "Uploading":
                hass.data[DOMAIN][entry.entry_id]["status"] = "Idle"
            return False, 0, "No sensor samples found in database for the requested window"

        latitude = hass.config.latitude
        longitude = hass.config.longitude
        location = f"{latitude}, {longitude}"

        try:
            hass.data[DOMAIN][entry.entry_id]["status"] = "Uploading"
            success, msg = await send_data(samples, location=location, device_id=device_id)

            if success:
                latest_ts = int(dt_util.utcnow().timestamp())
                hass.data[DOMAIN][entry.entry_id]["last_upload_ts"] = latest_ts
                hass.data[DOMAIN][entry.entry_id]["samples"] = []
                hass.data[DOMAIN][entry.entry_id]["status"] = "Idle"
                hass.data[DOMAIN][entry.entry_id]["last_upload"] = dt_util.utcnow().isoformat()
                hass.data[DOMAIN][entry.entry_id]["last_error"] = None

                _LOGGER.info("Upload successful (device_id: %s, %d samples): %s", device_id, len(samples), msg)
                return True, len(samples), msg
            else:
                hass.data[DOMAIN][entry.entry_id]["status"] = "Upload failed"
                hass.data[DOMAIN][entry.entry_id]["last_error"] = msg
                _LOGGER.error("Upload failed (device_id: %s): %s", device_id, msg)
                return False, len(samples), msg

        except Exception as err:
            hass.data[DOMAIN][entry.entry_id]["status"] = "Upload failed"
            hass.data[DOMAIN][entry.entry_id]["last_error"] = str(err)
            _LOGGER.error("Upload failed: %s", err)
            return False, len(samples), str(err)

    hass.data[DOMAIN][entry.entry_id]["upload_job"] = upload_job

    async def start_periodic_upload(now):
        _LOGGER.info("Starting periodic scheduled upload (interval: %ss)", UPLOAD_INTERVAL)

        remove_upload = async_track_time_interval(
            hass,
            upload_job,
            timedelta(seconds=UPLOAD_INTERVAL),
        )
        hass.data[DOMAIN][entry.entry_id]["remove_upload"] = remove_upload

        # Run scheduled upload
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
                    success, sample_count, detail_msg = await upload_job(now, force_sample_window=SAMPLE_INTERVAL)
                    if success and sample_count > 0:
                        await acknowledge_upload(
                            req_id,
                            "completed",
                            notes=f"Uploaded {sample_count} sensor samples successfully via on-demand trigger."
                        )
                    elif sample_count == 0:
                        await acknowledge_upload(
                            req_id,
                            "completed",
                            notes="On-demand trigger completed, but 0 sensor samples were found in the Home Assistant database for the past 24 hours."
                        )
                    else:
                        await acknowledge_upload(
                            req_id,
                            "failed",
                            notes=f"Upload of {sample_count} samples failed: {detail_msg}"
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

    # Schedule regular upload during off-peak night hours
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

        if target_time <= now_local:
            target_time += timedelta(days=1)

        delay = (target_time - now_local).total_seconds()

        _LOGGER.info(
            "First scheduled upload set for %s (in %.1f hours)",
            target_time.isoformat(),
            delay / 3600.0,
        )

    remove_start = async_call_later(
        hass,
        delay,
        start_periodic_upload,
    )
    hass.data[DOMAIN][entry.entry_id]["remove_start"] = remove_start

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data[DOMAIN].pop(entry.entry_id, {})

    if data.get("remove_upload"):
        data["remove_upload"]()

    if data.get("remove_start"):
        data["remove_start"]()

    if data.get("remove_poll"):
        data["remove_poll"]()

    return unload_ok
