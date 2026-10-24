"""Passive, in-memory diagnostics for controller traffic to the Pulsar meter."""

from __future__ import annotations

import json
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .crc import has_valid_crc
from .pulsar_protocol import parse_response

MAX_RECORDS = 4096

if TYPE_CHECKING:
    from .bionic_model import BionicModel


class CounterCheck:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._session_id: str | None = None
        self._started_monotonic_ns: int | None = None
        self._started_at: str | None = None
        self._records: list[dict[str, object]] = []
        self._last_report: dict[str, object] | None = None
        self._dropped = 0
        self._totals: dict[str, int] = {}
        self._last_volume_m3: float | None = None
        self._last_do22: bool | None = None

    def start(self) -> dict[str, object]:
        with self._lock:
            if self._active:
                return self._summary_locked(None)
            now = datetime.now(timezone.utc)
            self._session_id = f"counter-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
            self._started_monotonic_ns = time.monotonic_ns()
            self._started_at = now.isoformat()
            self._records = []
            self._dropped = 0
            self._totals = {
                "modbus": 0, "pulsar": 0, "successful": 0, "crc": 0,
                "protocol": 0, "no_response": 0, "pulsar_irrigation": 0,
                "do22_transitions": 0,
            }
            self._last_volume_m3 = None
            self._last_do22 = None
            self._active = True
            return self._summary_locked(None)

    def status(self, model: BionicModel | None = None) -> dict[str, object]:
        with self._lock:
            return self._summary_locked(model)

    def stop(self, home: Path, model: BionicModel | None = None) -> dict[str, object]:
        with self._lock:
            if not self._active:
                return dict(self._last_report or self._summary_locked(model))
            summary = self._summary_locked(model)
            summary["active"] = False
            summary["stoppedAt"] = datetime.now(timezone.utc).isoformat()
            report = {**summary, "observations": list(self._records)}
            self._active = False
            self._last_report = report
        directory = home / "counter-check-reports"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{report['sessionId']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        report["reportPath"] = str(path)
        with self._lock:
            self._last_report = dict(report)
        return report

    def observe(
        self,
        protocol: str,
        request: bytes,
        response: bytes,
        *,
        rx_started_ns: int,
        rx_completed_ns: int,
        response_started_ns: int,
        response_completed_ns: int,
        model: BionicModel | None,
    ) -> None:
        with self._lock:
            if not self._active:
                return
            request_crc = has_valid_crc(request)
            response_crc = bool(response) and has_valid_crc(response)
            address = request[:4].hex().upper() if protocol == "Pulsar" else (
                request[0] if request else None
            )
            function = request[4] if protocol == "Pulsar" and len(request) > 4 else (
                request[1] if len(request) > 1 else None
            )
            protocol_valid = request_crc
            volume_m3: float | None = None
            if protocol == "Pulsar" and response:
                try:
                    parsed = parse_response(
                        response,
                        address=request[:4].hex(),
                        function=1,
                        request_id=int.from_bytes(request[-4:-2], "little"),
                        payload_length=4,
                    )
                    volume_m3 = struct.unpack("<f", parsed.payload)[0]
                except (ValueError, RuntimeError, struct.error):
                    protocol_valid = False
            do22 = model.relay(22) if model is not None else None
            irrigation = (
                any(model.relay(tier.relay) for tier in model.tiers.values())
                if model is not None else None
            )
            key = "pulsar" if protocol == "Pulsar" else "modbus"
            self._totals[key] += 1
            if response and response_crc:
                self._totals["successful"] += 1
            if not request_crc or response and not response_crc:
                self._totals["crc"] += 1
            if not protocol_valid:
                self._totals["protocol"] += 1
            if not response:
                self._totals["no_response"] += 1
            if protocol == "Pulsar" and irrigation is True:
                self._totals["pulsar_irrigation"] += 1
            if volume_m3 is not None:
                self._last_volume_m3 = volume_m3
            if do22 is not None:
                if self._last_do22 is not None and self._last_do22 != do22:
                    self._totals["do22_transitions"] += 1
                self._last_do22 = do22
            if len(self._records) == MAX_RECORDS:
                self._records.pop(0)
                self._dropped += 1
            self._records.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "protocol": protocol,
                "address": address,
                "function": function,
                "requestLength": len(request),
                "requestCrcValid": request_crc,
                "responseLength": len(response),
                "responseCrcValid": response_crc,
                "protocolValid": protocol_valid,
                "rxStartedNs": rx_started_ns,
                "rxCompletedNs": rx_completed_ns,
                "responseStartedNs": response_started_ns,
                "responseCompletedNs": response_completed_ns,
                "responseFormationMs": (response_completed_ns - response_started_ns) / 1_000_000,
                "waterMeterLiters": model.water_meter.total_l if model is not None else None,
                "pulsarVolumeM3": volume_m3,
                "do22": do22,
                "irrigationActive": irrigation,
            })

    def _summary_locked(self, model: BionicModel | None) -> dict[str, object]:
        now_ns = time.monotonic_ns()
        records = self._records
        totals = self._totals
        started = self._started_monotonic_ns
        return {
            "active": self._active,
            "sessionId": self._session_id,
            "startedAt": self._started_at,
            "durationMs": (now_ns - started) // 1_000_000 if started is not None else 0,
            "retainedObservations": len(records),
            "lostObservations": self._dropped,
            "modbusRequests": totals.get("modbus", 0),
            "pulsarRequests": totals.get("pulsar", 0),
            "successfulResponses": totals.get("successful", 0),
            "crcErrors": totals.get("crc", 0),
            "protocolErrors": totals.get("protocol", 0),
            "observableTimeouts": 0,
            "observedNoResponse": totals.get("no_response", 0),
            "lastPulsarVolumeM3": self._last_volume_m3,
            "do22": model.relay(22) if model is not None else self._last_do22,
            "do22Transitions": totals.get("do22_transitions", 0),
            "irrigationActive": (any(model.relay(tier.relay) for tier in model.tiers.values())
                                  if model is not None else None),
            "pulsarDuringIrrigation": totals.get("pulsar_irrigation", 0),
            "timeoutNote": "Наблюдатель видит отсутствие ответа, но не подтверждает внутренний timeout firmware",
        }
