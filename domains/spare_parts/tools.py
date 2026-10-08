"""Service rules the desk reads from the company data. Deterministic: same data, same answer.

Ported from Predictive-Spare-Parts-Lab desk/tools.py (origin in docs/provenance.md). Only what
the text views need is here so far: when a scheduled part falls due. The lab's availability,
lead-time and service-plan rules are not ported yet (backlog R18).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .data import BomLine, ServiceData


def due_date(data: ServiceData, line: BomLine) -> Optional[date]:
    """When a scheduled part falls due on this machine; None if not scheduled or no history."""
    interval = data.parts[line.part_no].service_interval_months
    if not interval or not line.last_replaced:
        return None
    return line.last_replaced + timedelta(days=round(interval * 30.4))
