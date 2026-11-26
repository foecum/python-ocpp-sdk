"""Hypothesis profiles: a quick default and a large ``fuzz`` one (``fuzz.yml``, ``-m`` not needed).

Select with ``HYPOTHESIS_PROFILE=fuzz``; ``HYPOTHESIS_MAX_EXAMPLES`` overrides the count.
"""

import os

from hypothesis import HealthCheck, settings

_quiet = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
settings.register_profile("default", max_examples=60, deadline=None, suppress_health_check=_quiet)
settings.register_profile("fuzz", max_examples=5000, deadline=None, suppress_health_check=_quiet)
_profile = os.environ.get("HYPOTHESIS_PROFILE", "default")
_count = os.environ.get("HYPOTHESIS_MAX_EXAMPLES")
if _count:
    settings.register_profile("custom", settings.get_profile(_profile), max_examples=int(_count))
    _profile = "custom"
settings.load_profile(_profile)
