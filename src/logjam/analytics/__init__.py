"""Analytics: baselines, bottleneck detection, opportunity scoring.

Method in one paragraph
-----------------------
For every ``(entity, metric)`` time series we compute a *robust* rolling
baseline - trailing median and MAD (median absolute deviation) - and express
each day as a robust z-score ``(value - median) / (1.4826 * MAD)``. Median/MAD
rather than mean/std because port-call counts are spiky and we do not want a
single storm day to inflate the band for weeks. A large negative z on a
throughput or chokepoint-transit metric == flow is blocked (bottleneck). A
group-relative positive z on an alternative port == spare capacity is moving
(opportunity).
"""

from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks
from logjam.analytics.opportunity import detect_opportunities
from logjam.analytics.recovery import recovery_status

__all__ = [
    "compute_baselines",
    "detect_bottlenecks",
    "detect_opportunities",
    "recovery_status",
]
