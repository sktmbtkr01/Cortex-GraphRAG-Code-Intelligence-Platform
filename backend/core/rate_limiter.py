import asyncio
import time
from httpx import Response
from core.logger import get_logger

logger = get_logger(__name__)


class GitHubRateLimiter:
    """Handles GitHub API rate limits."""

    def __init__(self, buffer_requests: int = 100):
        self.buffer_requests = buffer_requests

    async def wait_if_needed(self, response: Response | None = None) -> None:
        """
        Check rate limit headers from a response. If remaining is less than buffer,
        sleep until the reset time.
        """
        if response is None:
            return

        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_epoch = response.headers.get("X-RateLimit-Reset")

        if remaining is None or reset_epoch is None:
            return

        try:
            remaining_int = int(remaining)
            reset_epoch_int = int(reset_epoch)
        except ValueError:
            return

        if remaining_int < self.buffer_requests:
            current_time = int(time.time())
            sleep_duration = max(0, reset_epoch_int - current_time)
            
            if sleep_duration > 0:
                logger.warning(
                    f"GitHub API rate limit critical ({remaining_int} left). "
                    f"Sleeping for {sleep_duration} seconds until reset."
                )
                await asyncio.sleep(sleep_duration + 1)  # +1s buffer
