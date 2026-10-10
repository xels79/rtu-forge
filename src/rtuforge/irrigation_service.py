"""A single polling worker; STOP is signalled without waiting for the bus lock."""
from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock, Thread
from time import monotonic

from .irrigation import IrrigationController, State
from .irrigation_config import IrrigationSettings
from .stand_hardware import StandHardware


class IrrigationService:
    def __init__(self, hardware: StandHardware, settings: IrrigationSettings,
                 bus_lock: RLock, report: Callable[[str], None]):
        self.hardware, self.settings = hardware, settings
        self.bus_lock, self.report = bus_lock, report
        hardware.report = report
        self.controller = IrrigationController(hardware, settings.limits(),
                                              confirm_timeout=settings.step_timeout_ms / 1000)
        self.stop_requested = Event()
        hardware.cancelled = self.stop_requested.is_set
        self.finished = Event()
        self.finished.set()
        self.thread: Thread | None = None
        self.gate = RLock()

    @property
    def busy(self) -> bool:
        return not self.finished.is_set() or self.controller.state != State.IDLE

    def start(self, rack: int, tier: int, liquid: str, hz: float, *, guided: bool = False) -> None:
        with self.gate:
            self.settings.require_commissioned()
            if self.busy:
                raise RuntimeError("Повторный START запрещён; выполните stop / reset fault")
            self.stop_requested.clear()
            drive, selector = self.settings.mapping(rack)
            self.controller.start(rack, tier, liquid, hz, drive=drive, selector=selector, guided=guided)
            self.report(f"Пуск {'по шагам' if guided else 'автоматический'}: стеллаж {rack}, ярус {tier}; клапан — реле {self.controller.valve}; выбор НВД — {selector}; бульон — 23; подпор — 1; FWD IDD {drive} — {32 if drive == 7 else 31}; задание {hz:g} Гц")
            self.finished.clear()
            self.thread = Thread(target=self._run, name="standforge-irrigation", daemon=True)
            try:
                self.thread.start()
            except Exception:
                self.controller.emergency("Не удалось запустить цикл управления")
                self.finished.set()
                raise

    def confirm_step(self) -> None:
        step = self.controller.pending_step
        if step is None or self.stop_requested.is_set():
            raise RuntimeError("Нет ожидающего подтверждения шага; Enter заранее не сохраняется")
        with self.bus_lock:
            if self.stop_requested.is_set():
                raise RuntimeError("STOP уже принят; подтверждение шага отменено")
            self.controller.confirm_step(step.number)
            self.report(f"Шаг {step.number}: Enter принят; проверки повторятся перед действием")

    def _telemetry(self) -> None:
        ctl = self.controller
        sample = ctl.last
        if sample is None:
            return
        current = f"{sample.drive_current_a:g} А" if sample.drive_current_a is not None else "нет измерения"
        relays = (", ".join(str(i + 1) for i, value in enumerate(self.hardware.last_coils) if value)
                  or "нет") if self.hardware.last_coils is not None else "нет измерения"
        self.report(f"Измерения: НВД={sample.low_bar:g} бар; ДВД={sample.high_bar:g} бар; IDD {ctl.drive}: {sample.hz:g} Гц, ток={current}, {'RUN' if sample.running else 'STOP'}; включены реле: {relays}")

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
        announced_step = 0
        next_telemetry = 0.0
        try:
            while True:
                with self.bus_lock:
                    ctl = self.controller
                    if self.stop_requested.is_set() and ctl.state != State.STOPPING:
                        ctl.stop()
                    before = ctl.state
                    ctl.tick()
                    now = monotonic()
                    step = ctl.pending_step
                    new_step = step is not None and step.number != announced_step
                    if now >= next_telemetry or ctl.state != previous or new_step:
                        if before != State.STOPPING:
                            self._telemetry()
                        elif ctl.last_stop_hz is not None:
                            self.report(f"Останов IDD {ctl.drive}: фактическая частота {ctl.last_stop_hz:g} Гц; ожидание подтверждённого STOP")
                        next_telemetry = now + self.settings.telemetry_ms / 1000
                    if new_step:
                        self.report(f"Шаг {step.number}: {step.description}. Enter — подтвердить; stop — остановить. Тайм-аут {self.settings.step_timeout_ms} мс")
                        announced_step = step.number
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
