"""Performance profiling utilities."""

import functools
import os
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def _is_profiling_enabled() -> bool:
    """Check if MELLEA_PROFILE env var enables profiling.

    Accepts 1, true, yes, on (case-insensitive). Any other value disables it.
    """
    val = os.environ.get("MELLEA_PROFILE", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def profile_if_enabled(func: F) -> F:
    """Wrap a function to profile it if MELLEA_PROFILE env var is set.

    Uses yappi to profile all threads (main, fixture workers, asyncio.to_thread
    workers, etc.), capturing time from ThreadPoolExecutor fan-out in certify
    and Guardian's asyncio.to_thread LLM calls that cProfile would miss.

    Set MELLEA_PROFILE=1 to enable profiling of the command.
    Profiling results include per-thread summaries and top 40 functions by
    total time, printed to stdout after the command completes.

    Requires yappi: install via `pip install -e '.[profile]'`

    Example:
        MELLEA_PROFILE=1 mellea-skills compile spec.yaml
        MELLEA_PROFILE=1 mellea-skills certify <pipeline_dir> -n 3
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not _is_profiling_enabled():
            return func(*args, **kwargs)

        try:
            import yappi
        except ImportError:
            raise RuntimeError(
                "Profiling requires yappi. Install it with:\n"
                "  pip install -e '.[profile]'"
            ) from None

        yappi.set_clock_type("WALL")
        yappi.start()
        try:
            result = func(*args, **kwargs)
        finally:
            yappi.stop()
            print("\n" + "=" * 80)
            print("PROFILING RESULTS (MELLEA_PROFILE=1)")
            print("=" * 80)

            thread_stats = yappi.get_thread_stats()
            print("\nPer-thread summary:")
            for stat in thread_stats:
                print(
                    f"  Thread {stat.id:5d} ({stat.name:20s}): {stat.ttot:10.3f}s"
                )

            print("\nTop 40 functions by total time:")
            func_stats = yappi.get_func_stats()
            func_stats.sort("ttot", sort_order="desc")

            for idx, stat in enumerate(func_stats[:40], 1):
                module_name = stat.module
                func_name = stat.name
                ttot = stat.ttot
                print(f"  {idx:2d}. {module_name}:{func_name:40s} {ttot:10.3f}s")

            yappi.clear_stats()
        return result
    return wrapper
