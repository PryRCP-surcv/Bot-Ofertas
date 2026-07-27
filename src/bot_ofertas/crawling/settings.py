"""Conservative Scrapy defaults for public product-price observations."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

BOT_NAME = "bot_ofertas"

SPIDER_MODULES = ["bot_ofertas.crawling.spiders"]
NEWSPIDER_MODULE = "bot_ofertas.crawling.spiders"
ITEM_PIPELINES = {
    "bot_ofertas.crawling.pipelines.PostgresPriceObservationPipeline": 300,
}

# Identify the client truthfully. A real contact URL/email can be appended before
# deploying this outside a developer machine.
USER_AGENT = os.environ.get(
    "BOT_USER_AGENT",
    "BotOfertas/0.1 (public-price-monitor; no-purchase)",
)
ROBOTSTXT_USER_AGENT = "BotOfertas"
ROBOTSTXT_OBEY = True

# One quiet request stream per store. AutoThrottle may slow this down further.
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 10.0
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_MAXSIZE = 5 * 1024 * 1024
DOWNLOAD_WARNSIZE = 3 * 1024 * 1024

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 10.0
AUTOTHROTTLE_MAX_DELAY = 120.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5
AUTOTHROTTLE_DEBUG = False

# The catalog endpoint does not need sessions. Disabling cookies also prevents
# accidental state from being carried into unrelated parts of the shop.
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

# Retry only a narrow set of transient server/network failures once. A 403, 429,
# or 503 is deliberately excluded: the spider treats each as a stop signal and
# never tries to bypass it.
RETRY_ENABLED = True
RETRY_TIMES = 1
RETRY_HTTP_CODES = [408, 500, 502, 504, 522, 524]
RETRY_PRIORITY_ADJUST = -1

# A five-minute development cache avoids duplicate requests caused by immediate
# reruns. Scheduled observations should be spaced much farther apart than this.
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 300
HTTPCACHE_DIR = "data/httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [403, 408, 429, 500, 502, 503, 504, 522, 524]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
