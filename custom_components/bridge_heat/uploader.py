# bridge_heat_sender.py
# Part of the Bridge Heat Home Assistant custom integration.
# Responsible for securely transmitting environmental sensor data
# (temperature, humidity, etc.) collected from participants' homes
# to the BGU geo-sensors research server.

import io
import gzip
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import quote
from .const import KEY, URL, PENDING_UPLOADS_URL, ACKNOWLEDGE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    device_id: Optional[str] = None,
    retries: int = 3,
    timeout: int = 60,
    chunk_size: int = 1500,
) -> Tuple[bool, str]:
    """
    Securely sends sensor data to the BGU geo-sensors server in chunked batches.

    Returns:
        Tuple of (success: bool, message: str)
    """

    if not samples:
        logger.warning("No samples to send.")
        return False, "No samples to send."

    total_samples = len(samples)
    chunks = [samples[i:i + chunk_size] for i in range(0, total_samples, chunk_size)]
    logger.info("Transmitting %d samples in %d chunk(s)...", total_samples, len(chunks))

    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "X-API-Key": KEY,
    }

    client_timeout = aiohttp.ClientTimeout(total=timeout)

    for chunk_idx, chunk in enumerate(chunks, 1):
        payload = {
            "samples": [
                {
                    **sample,
                    "time": (
                        sample["time"].isoformat()
                        if isinstance(sample.get("time"), datetime)
                        else str(sample.get("time"))
                    ),
                }
                for sample in chunk
            ]
        }

        if device_id:
            payload["device_id"] = device_id

        if location:
            payload["location"] = location

        try:
            compressed = await compress_payload(payload)
        except Exception as e:
            logger.error("Payload compression failed for chunk %d: %s", chunk_idx, e)
            return False, f"Payload compression failed: {e}"

        chunk_success = False
        last_error = ""

        for attempt in range(1, retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=client_timeout) as session:
                    async with session.post(URL, data=compressed, headers=headers, ssl=False) as resp:
                        resp_text = await resp.text()
                        if resp.status in (200, 201):
                            logger.info("Chunk %d/%d sent successfully on attempt %d.", chunk_idx, len(chunks), attempt)
                            chunk_success = True
                            break
                        else:
                            last_error = f"HTTP {resp.status}: {resp_text[:200]}"
                            logger.error("Server returned HTTP %s on chunk %d: %s", resp.status, chunk_idx, resp_text)
                            # Client error (4xx) means invalid request/payload, do not retry
                            if 400 <= resp.status < 500:
                                return False, f"Server rejected data (HTTP {resp.status}): {resp_text[:200]}"

            except aiohttp.ClientSSLError:
                logger.error("SSL verification failed.")
                return False, "SSL verification failed."

            except asyncio.TimeoutError:
                last_error = f"Timeout ({timeout}s) waiting for server response"
                logger.warning("Attempt %d on chunk %d timed out.", attempt, chunk_idx)

            except aiohttp.ClientError as e:
                last_error = f"Network error: {e}"
                logger.error("Attempt %d on chunk %d failed: %s", attempt, chunk_idx, e)

            if attempt < retries:
                await asyncio.sleep(2 ** attempt)

        if not chunk_success:
            logger.error("Chunk %d/%d failed after %d retries. Last error: %s", chunk_idx, len(chunks), retries, last_error)
            return False, f"Upload failed on chunk {chunk_idx}/{len(chunks)}: {last_error}"

    return True, f"Successfully uploaded {total_samples} samples across {len(chunks)} chunk(s)."


async def check_pending_uploads(
    device_id: Optional[str] = None,
    location: Optional[str] = None,
    timeout: int = 15,
) -> list[dict]:
    """
    Poll the backend to check if any on-demand upload requests are pending
    for this device (by UUID and/or location).
    """
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    headers = {
        "X-API-Key": KEY,
        "Accept": "application/json",
    }
    params = []
    if device_id:
        params.append(f"device_id={quote(device_id)}")
    if location:
        params.append(f"location={quote(location)}")

    query_str = f"?{'&'.join(params)}" if params else ""
    url = f"{PENDING_UPLOADS_URL}{query_str}"

    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("requests", [])
                logger.warning(f"Pending uploads poll returned status {resp.status}")
                return []
    except Exception as e:
        logger.debug(f"Failed to check pending uploads: {e}")
        return []


async def acknowledge_upload(
    request_id: int,
    status: str,
    notes: Optional[str] = None,
    timeout: int = 15,
) -> bool:
    """
    Acknowledge or update the status of an on-demand upload request
    (e.g. 'acknowledged', 'completed', or 'failed').
    """
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    headers = {
        "X-API-Key": KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = f"{ACKNOWLEDGE_URL}/{request_id}"
    payload = {"status": status}
    if notes:
        payload["notes"] = notes

    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(url, json=payload, headers=headers, ssl=False) as resp:
                if resp.status in (200, 201):
                    return True
                logger.warning(f"Acknowledge upload #{request_id} returned status {resp.status}")
                return False
    except Exception as e:
        logger.error(f"Failed to acknowledge upload #{request_id}: {e}")
        return False
