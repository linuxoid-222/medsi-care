"""Observable detector input; evaluation labels cannot cross this boundary."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MethodInput:
    profile_id: str
    day_index: int
    sleep_hours: float | None
    activity_minutes: float | None
    pulse_bpm: float | None
    check_in_text: str
    quality: str

    @property
    def completeness(self) -> float:
        return sum(value is not None for value in (
            self.sleep_hours, self.activity_minutes, self.pulse_bpm
        )) / 3
