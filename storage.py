
import json
import redis

import streamlit as st

from config import DATA_TTL_SECONDS, TIMEZONE


@st.cache_resource
def get_redis():
    redis_url = st.secrets.get("REDIS_URL")

    if not redis_url:
        raise RuntimeError(
            "REDIS_URL is missing from Streamlit secrets."
        )

    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_timeout=5,
    )


def get_daily_key():
    today = datetime_now().strftime("%Y-%m-%d")
    return f"nems:daily:{today}"


def datetime_now():
    from datetime import datetime
    return datetime.now(TIMEZONE)


def load_patients():
    client = get_redis()
    key = get_daily_key()

    raw = client.get(key)

    if not raw:
        return []

    return json.loads(raw)


def save_patients(patients):
    client = get_redis()
    key = get_daily_key()

    lock = client.lock(
        f"{key}:lock",
        timeout=10,
        blocking_timeout=5,
    )

    with lock:
        client.set(
            key,
            json.dumps(patients),
            ex=DATA_TTL_SECONDS,
        )


def reset_patients():
    client = get_redis()
    client.delete(get_daily_key())
