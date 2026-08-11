"""Learn a durable STB MAC only after SGS has verified the target IP.

The healthy command path must remain fast.  ``learn_verified_mac_async`` only
starts a daemon worker; ARP inspection and persistence happen after the SGS
response has already succeeded.  The learner never performs receiver identity
probing and never replaces a different persisted MAC automatically.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional

from . import ip_recovery
from .stb_store import store

LOG = logging.getLogger(__name__)
_MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.I)
_lock = threading.RLock()
_active: set[str] = set()


def _normalize_mac(value: object) -> str:
    return str(value or "").replace("-", ":").lower().strip()


def _valid_mac(value: object) -> Optional[str]:
    normalized = _normalize_mac(value)
    return normalized if _MAC_RE.fullmatch(normalized) else None


def learn_verified_mac(
    alias: str,
    verified_ip: str,
    *,
    store_obj: Any = None,
    arp_reader: Optional[Callable[[], Mapping[str, str]]] = None,
) -> Dict[str, Any]:
    """Persist the ARP MAC for an IP that has just completed authenticated SGS.

    ``verified_ip`` is trusted only because the caller invokes this function
    after SGS returned success.  We still refuse to persist if the configured IP
    has changed in the meantime, and an existing different MAC is never
    overwritten automatically.
    """
    alias = str(alias or "").strip()
    verified_ip = str(verified_ip or "").strip()
    target_store = store_obj or store
    if not alias or not verified_ip:
        return {"learned": False, "reason": "alias_and_ip_required"}

    entry = dict(target_store.get(alias) or {})
    if not entry:
        return {"learned": False, "reason": "alias_not_found"}
    configured_ip = str(entry.get("ip") or "").strip()
    if configured_ip != verified_ip:
        return {
            "learned": False,
            "reason": "configured_ip_changed",
            "configured_ip": configured_ip,
            "verified_ip": verified_ip,
        }

    existing = _valid_mac(entry.get("mac"))
    reader = arp_reader or ip_recovery._arp_entries
    observed = _valid_mac((reader() or {}).get(verified_ip))
    if not observed:
        # A successful same-subnet SGS exchange normally populates ARP already.
        # Give the OS a few scheduler ticks to publish the cache entry, without
        # issuing identity probes or adding latency to the completed HTTP request.
        for _ in range(3):
            time.sleep(0.05)
            observed = _valid_mac((reader() or {}).get(verified_ip))
            if observed:
                break
    if not observed:
        return {"learned": False, "reason": "arp_mac_unavailable"}

    state = ip_recovery._state(alias)
    if existing:
        state.known_mac = existing
        if existing != observed:
            LOG.warning(
                "refusing verified MAC replacement alias=%s ip=%s persisted=%s observed=%s",
                alias,
                verified_ip,
                existing,
                observed,
            )
            return {
                "learned": False,
                "reason": "existing_mac_mismatch",
                "mac": existing,
                "observed_mac": observed,
            }
        return {"learned": False, "reason": "already_persisted", "mac": existing}

    # Re-read immediately before writing so a concurrent GUI/IP update cannot
    # bind a MAC learned for the old address to a newly configured address.
    latest = dict(target_store.get(alias) or {})
    if str(latest.get("ip") or "").strip() != verified_ip:
        return {
            "learned": False,
            "reason": "configured_ip_changed",
            "configured_ip": str(latest.get("ip") or "").strip(),
            "verified_ip": verified_ip,
        }
    latest_existing = _valid_mac(latest.get("mac"))
    if latest_existing and latest_existing != observed:
        return {
            "learned": False,
            "reason": "existing_mac_mismatch",
            "mac": latest_existing,
            "observed_mac": observed,
        }

    target_store.update_stb(
        alias,
        {
            "mac": observed,
            "mac_learned_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mac_learning_source": "verified_sgs_arp",
        },
        create=False,
    )
    state.known_mac = observed
    LOG.info("persisted verified SGS MAC alias=%s ip=%s mac=%s", alias, verified_ip, observed)
    return {"learned": True, "reason": "verified_sgs_arp", "mac": observed}


def learn_verified_mac_async(alias: str, verified_ip: str) -> bool:
    """Schedule verified-MAC learning without blocking a successful SGS reply."""
    alias = str(alias or "").strip()
    verified_ip = str(verified_ip or "").strip()
    if not alias or not verified_ip:
        return False

    entry = dict(store.get(alias) or {})
    existing = _valid_mac(entry.get("mac"))
    if existing:
        ip_recovery._state(alias).known_mac = existing
        return False

    with _lock:
        if alias in _active:
            return False
        _active.add(alias)

    def worker() -> None:
        try:
            learn_verified_mac(alias, verified_ip)
        except Exception:
            LOG.exception("verified MAC learning failed alias=%s ip=%s", alias, verified_ip)
        finally:
            with _lock:
                _active.discard(alias)

    threading.Thread(
        target=worker,
        name=f"VerifiedMac-{alias}",
        daemon=True,
    ).start()
    return True
