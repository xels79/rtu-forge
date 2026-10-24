"""Persistent equipment-health profiles and deterministic damage progression."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from math import inf


EQUIPMENT_IDS = ("bo-to-bp", "bso1-to-bp", "bso2-to-bp", "hp1", "hp2")
EQUIPMENT_STATES = {"HEALTHY", "DRY_RUNNING", "OVERHEATED", "DEGRADED", "FAILED"}
FAILURE_TYPES = {"jammed", "impeller_damage", "motor_failure", "loss_of_prime"}


@dataclass(frozen=True)
class EquipmentProfile:
    dry_run_warning_s: float
    overheat_s: float
    degrade_s: float
    failure_s: float
    heating_rate_per_s: float
    cooling_rate_per_s: float
    wear_rate_per_s: float
    wear_flow_reduction: float
    initial_state: str
    failure_type: str


@dataclass(frozen=True)
class EquipmentLifetime:
    """Explain the two independent dry-run failure mechanisms."""

    threshold_s: float
    wear_s: float
    effective_s: float
    limiting_mechanism: str


def lifetime_for_new_equipment(profile: EquipmentProfile) -> EquipmentLifetime:
    """Return dry-run lifetime for a new, undamaged pump.

    Wear starts only after ``dry_run_warning_s`` in :meth:`EquipmentHealth.update`.
    The direct ``failure_s`` timer and accumulated wear are independent.
    """
    wear_s = (
        profile.dry_run_warning_s + 1.0 / profile.wear_rate_per_s
        if profile.wear_rate_per_s > 0 else inf
    )
    effective = min(profile.failure_s, wear_s)
    if profile.failure_s < wear_s:
        mechanism = "failure_s"
    elif wear_s < profile.failure_s:
        mechanism = "wear_rate_per_s"
    else:
        mechanism = "одновременно"
    return EquipmentLifetime(profile.failure_s, wear_s, effective, mechanism)


def remaining_dry_run_s(health: EquipmentHealth) -> float:
    """Return time to failure if the current dry run continues."""
    if health.failed or health.damage >= 1.0:
        return 0.0
    direct = max(0.0, health.profile.failure_s - health.dry_run_s)
    if health.profile.wear_rate_per_s <= 0:
        wear = inf
    else:
        warning_wait = max(0.0, health.profile.dry_run_warning_s - health.dry_run_s)
        wear = warning_wait + max(0.0, 1.0 - health.damage) / health.profile.wear_rate_per_s
    return min(direct, wear)


def synchronize_wear_rate(profile: EquipmentProfile) -> EquipmentProfile:
    """Make wear reach 100% at ``failure_s`` for new equipment."""
    accumulation_s = profile.failure_s - profile.dry_run_warning_s
    if accumulation_s <= 0:
        raise ValueError("failure_s должен быть больше dry_run_warning_s для синхронизации износа")
    return replace(profile, wear_rate_per_s=1.0 / accumulation_s)


def _profile(failure_type: str, *, hp: bool = False) -> EquipmentProfile:
    return EquipmentProfile(
        dry_run_warning_s=5.0,
        overheat_s=45.0 if hp else 30.0,
        degrade_s=90.0 if hp else 60.0,
        failure_s=180.0 if hp else 120.0,
        heating_rate_per_s=1.0 / (45.0 if hp else 30.0),
        cooling_rate_per_s=0.02,
        wear_rate_per_s=1.0 / (180.0 if hp else 120.0),
        wear_flow_reduction=0.8,
        initial_state="HEALTHY",
        failure_type=failure_type,
    )


FACTORY_EQUIPMENT_PROFILES: dict[str, EquipmentProfile] = {
    "bo-to-bp": _profile("motor_failure"),
    "bso1-to-bp": _profile("jammed"),
    "bso2-to-bp": _profile("impeller_damage"),
    "hp1": _profile("impeller_damage", hp=True),
    "hp2": _profile("jammed", hp=True),
}
FACTORY_EQUIPMENT_PROFILE = json.dumps(
    {equipment_id: asdict(profile) for equipment_id, profile in FACTORY_EQUIPMENT_PROFILES.items()},
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
)


def parse_equipment_profile(value: str) -> dict[str, EquipmentProfile]:
    try:
        raw = json.loads(value)
        profiles = {
            equipment_id: EquipmentProfile(**raw[equipment_id])
            for equipment_id in EQUIPMENT_IDS
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("Профиль оборудования повреждён или неполон") from None
    validate_equipment_profiles(profiles)
    return profiles


def serialize_equipment_profiles(profiles: dict[str, EquipmentProfile]) -> str:
    validate_equipment_profiles(profiles)
    return json.dumps(
        {equipment_id: asdict(profiles[equipment_id]) for equipment_id in EQUIPMENT_IDS},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def validate_equipment_profiles(profiles: dict[str, EquipmentProfile]) -> None:
    if set(profiles) != set(EQUIPMENT_IDS):
        raise ValueError("Профиль должен описывать все пять насосов")
    for equipment_id, profile in profiles.items():
        times = (
            profile.dry_run_warning_s, profile.overheat_s,
            profile.degrade_s, profile.failure_s,
        )
        if not 0 <= times[0] <= times[1] <= times[2] <= times[3]:
            raise ValueError(f"{equipment_id}: времена должны возрастать от предупреждения до отказа")
        if min(profile.heating_rate_per_s, profile.cooling_rate_per_s, profile.wear_rate_per_s) < 0:
            raise ValueError(f"{equipment_id}: скорости нагрева, охлаждения и износа не могут быть отрицательными")
        if not 0 <= profile.wear_flow_reduction <= 1:
            raise ValueError(f"{equipment_id}: снижение производительности должно быть 0..1")
        if profile.initial_state not in EQUIPMENT_STATES:
            raise ValueError(f"{equipment_id}: неизвестное начальное состояние")
        if profile.failure_type not in FAILURE_TYPES:
            raise ValueError(f"{equipment_id}: неизвестный тип критического отказа")


@dataclass
class EquipmentHealth:
    profile: EquipmentProfile
    state: str = "HEALTHY"
    dry_running: bool = False
    dry_run_s: float = 0.0
    total_dry_run_s: float = 0.0
    heat: float = 0.0
    damage: float = 0.0
    failure: str = "none"
    warning_active: bool = False
    replacements: int = 0

    @classmethod
    def create(cls, profile: EquipmentProfile) -> EquipmentHealth:
        health = cls(profile=profile)
        health.apply_initial_state()
        return health

    def apply_initial_state(self) -> None:
        self.state = self.profile.initial_state
        if self.state == "OVERHEATED":
            self.heat = 1.0
        elif self.state == "DEGRADED":
            self.damage = 0.5
        elif self.state == "FAILED":
            self.damage = 1.0
            self.failure = self.profile.failure_type

    @property
    def failed(self) -> bool:
        return self.failure != "none"

    @property
    def repair_required(self) -> bool:
        return self.failed or self.damage > 0

    @property
    def performance_factor(self) -> float:
        if self.failure in {"jammed", "motor_failure"}:
            return 0.0
        if self.failure == "impeller_damage":
            return 0.2
        if self.failure == "loss_of_prime":
            return 0.05
        if self.failure == "dry_run_wear":
            return max(0.0, 1.0 - self.damage)
        return max(0.0, 1.0 - self.damage * self.profile.wear_flow_reduction)

    def configure(self, profile: EquipmentProfile, *, initial: bool = False) -> None:
        self.profile = profile
        if initial:
            self.repair()
            self.apply_initial_state()

    def update(self, commanded: bool, water_available: bool, dt_s: float) -> tuple[str, bool]:
        previous_state = self.state
        previous_warning = self.warning_active
        if self.failed:
            self.dry_running = False
            self.dry_run_s = 0.0
            self.heat = max(0.0, self.heat - self.profile.cooling_rate_per_s * dt_s)
            self.state = "FAILED"
            return previous_state, previous_warning

        self.dry_running = commanded and not water_available
        if self.dry_running:
            self.dry_run_s += dt_s
            self.total_dry_run_s += dt_s
            self.warning_active = self.dry_run_s >= self.profile.dry_run_warning_s
            if self.warning_active:
                self.heat = min(1.0, self.heat + self.profile.heating_rate_per_s * dt_s)
                self.damage = min(1.0, self.damage + self.profile.wear_rate_per_s * dt_s)
            if self.dry_run_s >= self.profile.failure_s or self.damage >= 1.0:
                self.failure = self.profile.failure_type
                self.state = "FAILED"
            elif self.dry_run_s >= self.profile.degrade_s:
                self.state = "DEGRADED"
            elif self.dry_run_s >= self.profile.overheat_s or self.heat >= 1.0:
                self.state = "OVERHEATED"
            else:
                self.state = "DRY_RUNNING"
        else:
            self.dry_run_s = 0.0
            self.warning_active = False
            self.heat = max(0.0, self.heat - self.profile.cooling_rate_per_s * dt_s)
            self.state = "DEGRADED" if self.damage > 0 else "HEALTHY"
        return previous_state, previous_warning

    def repair(self) -> None:
        self.state = "HEALTHY"
        self.dry_running = False
        self.dry_run_s = 0.0
        self.heat = 0.0
        self.damage = 0.0
        self.failure = "none"
        self.warning_active = False

    def replace(self) -> None:
        self.repair()
        self.replacements += 1
