# bridge_heat_sender.py
# Part of the Bridge Heat Home Assistant custom integration.
# Responsible for securely transmitting environmental sensor data
# (temperature, humidity, etc.) collected from participants' homes
# to the BGU geo-sensors research server.

import os
import io
import gzip
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_URL = "https://bgu-geo-sensors.com/upload/"

API_KEY = os.environ.get("BRIDGE_HEAT_API_KEY")


def _compress_payload_sync(payload: dict) -> bytes:
    json_bytes = json.dumps(payload).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(json_bytes)
    return buf.getvalue()


async def compress_payload(payload: dict) -> bytes:
    """Serialises payload to JSON and gzip-compresses it in a thread pool.

    Offloaded via asyncio.to_thread so the HA event loop is never blocked
    by the CPU-bound compression work.
    """
    return await asyncio.to_thread(_compress_payload_sync, payload)


async def send_data(
    samples: list[dict],
    location: Optional[str] = None,
    retries: int = 3,
    timeout: int = 10
) -> bool:
    """
    Securely sends sensor data to the BGU geo-sensors server.

    Args:
        samples:  List of dicts containing sensor readings.
        All values are strings except 'time' (a datetime object).
        An optional 'location' key may also be present per sample.
        location: Optional study-site or household identifier to attach
        to the entire batch (separate from per-sample location).
        retries:  How many times to retry on transient network errors.
        Client/auth errors and SSL failures are never retried.
        timeout:  Seconds to wait for a server response before giving up.

    Returns:
        True if the server accepted the payload, False on any failure.
    """

    if not samples:
        logger.warning("No samples to send.")
        return False

    payload = {
        "samples": [
            {
                **sample,
                "time": (
                    sample["time"].isoformat()
                    if isinstance(sample.get("time"), datetime)
                    else sample.get("time")
                ),
            }
            for sample in samples
        ]
    }

    if location:
        payload["location"] = location

    try:
        compressed = await compress_payload(payload)
    except (TypeError, ValueError, OSError) as e:
        logger.error(f"Payload compression failed: {e}")
        return False

    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "X-API-Key": API_KEY,
    }

    client_timeout = aiohttp.ClientTimeout(total=timeout)

    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(SERVER_URL, data=compressed, headers=headers, ssl=True) as resp:
                    resp.raise_for_status()
                    logger.info(f"Data sent successfully on attempt {attempt}.")
                    return True

        except aiohttp.ClientSSLError:
            # SSL error means the server's certificate is invalid or a
            # man-in-the-middle attack is in progress. Never disable ssl=True
            # as a workaround — that would expose participants' data.
            logger.error("SSL verification failed. Do not disable SSL verification!")
            return False

        except asyncio.TimeoutError:
            logger.warning(f"Attempt {attempt} timed out.")

        except aiohttp.ClientResponseError as e:
            logger.error(f"HTTP error: {e.status} - {e.message}")
            # 4xx errors mean our request is wrong — retrying won't help.
            if e.status in (400, 401, 403):
                return False

        except aiohttp.ClientError as e:
            logger.error(f"Request failed: {e}")

        if attempt < retries:
            await asyncio.sleep(2 ** attempt)

    logger.error("All retry attempts failed.")
    return False
