"""Conservative SGS IP recovery with injected RF/OCR fallback hooks."""
from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

import requests
from .stb_store import store

LOG = logging.getLogger(__name__)
_RXID_RE = re.compile(r"R\d{10}(?:-\d{2})?", re.I)
_IP_RE = re.compile(r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)")


@dataclass(frozen=True)
class FailureClass:
    recoverable: bool
    auth: bool = False
    wrong_device: bool = False
    transport: bool = False
    reason: str = "unknown"


@dataclass(frozen=True)
class RecoveryResult:
    ok: bool
    alias: str
    old_ip: str
    new_ip: Optional[str] = None
    strategy: Optional[str] = None
    reason: Optional[str] = None


def classify_sgs_failure(exc: BaseException | str) -> FailureClass:
    text = str(exc).strip().lower()
    if not text:
        return FailureClass(False, reason="empty_error")
    if any(token in text for token in ("401", "403", "digest", "credential", "auth_required", "pair first")):
        return FailureClass(False, auth=True, reason="authentication")
    if any(token in text for token in ("wrong receiver", "wrong device", "rxid mismatch", "identity mismatch")):
        return FailureClass(False, wrong_device=True, reason="identity")
    if any(token in text for token in ("timed out", "timeout", "connection refused", "no route", "unreachable", "name resolution", "connection aborted", "max retries")):
        return FailureClass(True, transport=True, reason="transport")
    return FailureClass(False, reason="application")


def extract_ipv4(text: str) -> list[str]:
    out = []
    for match in _IP_RE.findall(text or ""):
        try:
            ip = ipaddress.ip_address(match)
        except ValueError:
            continue
        if ip.version == 4 and (ip.is_private or ip.is_link_local) and not (ip.is_reserved or ip.is_unspecified or ip.is_loopback or ip.is_multicast):
            out.append(str(ip))
    return list(dict.fromkeys(out))


def _network_for(ip: str) -> ipaddress.IPv4Network:
    address = ipaddress.ip_address(ip)
    if address.version != 4:
        raise ValueError("only IPv4 SGS recovery is supported")
    return ipaddress.ip_network(f"{address}/24", strict=False)


def _default_probe(ip: str, expected_rxid: str, timeout: float = 0.7) -> bool:
    for port in (8080, 80):
        url = f"http://{ip}:{port}/www/sgs"
        for payload in ({"command": "get_stb_information"}, {"command": "get_receiver_id"}):
            try:
                data = requests.post(url, json=payload, timeout=timeout).json()
            except Exception:
                continue
            ids = {rid.upper() for rid in _RXID_RE.findall(repr(data))}
            if expected_rxid.upper() in ids:
                return True
    return False


def scan_candidates(last_ip: str, expected_rxid: str, *, probe: Callable[[str, str], bool] = _default_probe, candidates: Optional[Iterable[str]] = None) -> list[str]:
    hosts = candidates if candidates is not None else (str(host) for host in _network_for(last_ip).hosts())
    matches = []
    for candidate in hosts:
        if candidate == last_ip:
            continue
        try:
            if probe(candidate, expected_rxid):
                matches.append(candidate)
        except Exception as exc:
            LOG.debug("identity probe failed for %s: %s", candidate, exc)
    return matches


def recover_alias(alias: str, *, verify: Callable[[str, str], bool] = _default_probe, scan: Callable[[str, str], Sequence[str]] = scan_candidates, rf_navigator: Optional[Callable[[str], None]] = None, screen_ip_reader: Optional[Callable[[str], Optional[str]]] = None) -> RecoveryResult:
    info = store.get(alias) or {}
    old_ip = str(info.get("ip") or "")
    rxid = str(info.get("stb") or "")
    if not old_ip or not rxid:
        return RecoveryResult(False, alias, old_ip, reason="alias requires ip and RxID")
    matches = list(dict.fromkeys(scan(old_ip, rxid)))
    if len(matches) > 1:
        return RecoveryResult(False, alias, old_ip, reason=f"ambiguous identity matches: {matches}")
    candidate = matches[0] if matches else None
    strategy = "identity_scan" if candidate else None
    if candidate is None and screen_ip_reader is not None:
        if rf_navigator is not None:
            rf_navigator(alias)
        ips = extract_ipv4(screen_ip_reader(alias) or "")
        if len(ips) == 1:
            candidate, strategy = ips[0], "rf_screen"
        elif len(ips) > 1:
            return RecoveryResult(False, alias, old_ip, reason=f"ambiguous screen IPs: {ips}")
    if not candidate:
        return RecoveryResult(False, alias, old_ip, reason="no identity-verified replacement IP")
    if candidate == old_ip:
        return RecoveryResult(True, alias, old_ip, candidate, strategy or "unchanged")
    if not verify(candidate, rxid):
        return RecoveryResult(False, alias, old_ip, candidate, strategy, "candidate failed identity verification")
    store.update_stb(alias, {"ip": candidate, "ip_recovery_strategy": strategy})
    try:
        if not verify(candidate, rxid):
            raise RuntimeError("post-write verification failed")
    except Exception as exc:
        store.update_stb(alias, {"ip": old_ip})
        return RecoveryResult(False, alias, old_ip, candidate, strategy, str(exc))
    return RecoveryResult(True, alias, old_ip, candidate, strategy)
