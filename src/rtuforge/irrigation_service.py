"""A single polling worker; STOP is signalled without waiting for the bus lock."""
from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock, Thread

from .irrigation import IrrigationController, State
from .irrigation_config import IrrigationSettings
from .stand_hardware import StandHardware


class IrrigationService:
    def __init__(self, hardware: StandHardware, settings: IrrigationSettings,
                 bus_lock: RLock, report: Callable[[str], None]):
        self.hardware, self.settings = hardware, settings
        self.bus_lock, self.report = bus_lock, report
        self.controller = IrrigationController(hardware, settings.limits())
        self.stop_requested = Event()
        hardware.cancelled = self.stop_requested.is_set
        self.finished = Event()
        self.finished.set()
        self.thread: Thread | None = None
        self.gate = RLock()

    @property
    def busy(self) -> bool:
        return not self.finished.is_set() or self.controller.state != State.IDLE

    def start(self, rack: int, tier: int, liquid: str, percent: float) -> None:
        with self.gate:
            self.settings.require_commissioned()
            if self.busy:
                raise RuntimeError("Повторный START запрещён; выполните stop / reset fault")
            self.stop_requested.clear()
            drive, selector = self.settings.mapping(rack)
            self.controller.start(rack, tier, liquid, percent, drive=drive, selector=selector)
            self.finished.clear()
            self.thread = Thread(target=self._run, name="standforge-irrigation", daemon=True)
            try:
                self.thread.start()
            except Exception:
                self.controller.emergency("Не удалось запустить цикл управления")
                self.finished.set()
                raise

    def stop(self) -> None:
        self.stop_requested.set()
        if self.finished.is_set() and self.controller.state == State.FAULT:
            with self.gate:
                if self.finished.is_set():
                    self.finished.clear()
                    self.thread = Thread(target=self._run, name="standforge-stop", daemon=True)
                    self.thread.start()

    def _run(self) -> None:
        previous = None
        try:
            while True:
                with self.bus_lock:
                    ctl = self.controller
                    if self.stop_requested.is_set() and ctl.state != State.STOPPING:
                        ctl.stop()
                    ctl.tick()
                    if ctl.state != previous:
                        self.report(f"Полив: {ctl.state.value}" + (f" — {ctl.fault_reason}" if ctl.fault_reason else ""))
                        previous = ctl.state
                    if ctl.state in (State.IDLE, State.FAULT):
                        break
                # Event wakes polling immediately for STOP; avoid spinning during deceleration.
                if self.stop_requested.is_set():
                    Event().wait(self.settings.poll_ms / 1000)
                else:
                    self.stop_requested.wait(self.settings.poll_ms / 1000)
        except Exception as exc:
            # Unexpected worker failures still attempt all stop outputs before latching FAULT.
            with self.bus_lock:
                self.controller.emergency(f"Ошибка цикла управления: {exc}")
                self.controller._state(State.FAULT)
            self.report(self.controller.fault_reason)
        finally:
            self.finished.set()

    def reset_fault(self) -> None:
        with self.gate:
            if not self.finished.is_set():
                raise RuntimeError("Дождитесь завершения STOPPING перед reset fault")
            with self.bus_lock:
                self.controller.reset_fault()
            self.stop_requested.clear()

    def close(self) -> None:
        self.stop()
        if self.thread is not None:
            # Serial calls are bounded by connection.timeout_ms; the controller bounds STOPPING.
            self.thread.join()
        if self.controller.state == State.FAULT:
            self.report("Останов завершён с FAULT: " + self.controller.fault_reason)
