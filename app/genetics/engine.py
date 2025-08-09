from typing import Tuple

def simple_tick(age_days: int, health: float) -> Tuple[int, float]:
    """
    Day 1: plants just age; mild health decay with age.
    """
    age_days += 1
    health = max(0.0, min(1.0, health - 0.005))
    return age_days, health
