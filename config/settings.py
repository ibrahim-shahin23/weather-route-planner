"""Settings. Everything deploy-specific comes from environment variables."""
import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")  # local dev only; on Vercel use project env vars
except ImportError:
    pass


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


ON_VERCEL = bool(env("VERCEL"))

DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

# --- Hosts -------------------------------------------------------------------
# Prefer an explicit host in DJANGO_ALLOWED_HOSTS (e.g. your-api.vercel.app).
# The platform-provided hostnames below are added automatically.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
for _host_var in (
    "RENDER_EXTERNAL_HOSTNAME",
    "VERCEL_URL",
    "VERCEL_BRANCH_URL",
    "VERCEL_PROJECT_PRODUCTION_URL",
):
    if env(_host_var):
        ALLOWED_HOSTS.append(env(_host_var))
if not ALLOWED_HOSTS and not DEBUG:
    raise RuntimeError("Set DJANGO_ALLOWED_HOSTS (e.g. your-api.vercel.app).")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "apps.trips",
]

# CorsMiddleware must come before anything that can generate a response
# (Security, WhiteNoise, Common), otherwise preflights can lose their headers.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
USE_TZ = True
TIME_ZONE = "UTC"
DATABASES: dict = {}  # stateless: no database needed
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Never 301 /api/geocode -> /api/geocode/. Browsers refuse redirects on CORS
# preflights, so URL patterns should accept both forms (see urls note below):
#   re_path(r"^api/geocode/?$", ...)
APPEND_SLASH = False

# --- CORS / proxy ------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    o.rstrip("/")
    for o in env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
]
# Optional: regexes for Vercel preview deployments, comma-separated, e.g.
#   ^https://weather-route-planner-[a-z0-9-]+\.vercel\.app$
# (avoid commas inside a regex, e.g. {1,3}).
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_PREFLIGHT_MAX_AGE = 60 * 60 * 24  # cache preflights for a day

# Only relevant if you later add sessions/CSRF; harmless otherwise.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Vercel terminates TLS. Do NOT enable SECURE_SSL_REDIRECT here: it would answer
# the proxied http request with a redirect and break preflights.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --- Static SPA (only if the built React app is bundled with this service) ---
FRONTEND_DIST = Path(env("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist")))
if FRONTEND_DIST.exists():
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True

# --- Cache (weather + geocoding + throttling) ---------------------------------
# Vercel functions are serverless: LocMemCache is per-instance and is lost on
# every cold start, so throttling and caching barely work without Redis.
# Use a managed Redis (e.g. Upstash, rediss:// URL) and `pip install redis`.
REDIS_URL = env("REDIS_URL")
if ON_VERCEL and not REDIS_URL:
    logging.getLogger(__name__).warning(
        "REDIS_URL is not set: cache and rate limits are per-instance on Vercel."
    )
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if REDIS_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "trips", "OPTIONS": {"MAX_ENTRIES": 5000}}
    )
}

# --- DRF -----------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "apps.trips.api.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "analyze": env("THROTTLE_ANALYZE", "20/min"),
        "heatmap": env("THROTTLE_HEATMAP", "20/min"),
        "geocode": env("THROTTLE_GEOCODE", "120/min"),
        "light": "120/min",
    },
}
# Vercel's edge adds the client IP to X-Forwarded-For, so one proxy hop.
_num_proxies = env("NUM_PROXIES", "1" if ON_VERCEL else "")
if _num_proxies:
    REST_FRAMEWORK["NUM_PROXIES"] = int(_num_proxies)

# --- Third-party services --------------------------------------------------------
# The public OSRM and Photon servers require a real contact in the User-Agent
# and are not meant for heavy production traffic; self-host or use a paid tier
# if usage grows.
HTTP_USER_AGENT = env("HTTP_USER_AGENT", "weather-route-planner/1.0 (contact: set HTTP_USER_AGENT)")
OSRM_BASE_URL = env("OSRM_BASE_URL", "https://router.project-osrm.org")
PHOTON_BASE_URL = env("PHOTON_BASE_URL", "https://photon.komoot.io")
OPEN_METEO_BASE_URL = env("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_API_KEY = env("OPEN_METEO_API_KEY")

# --- Domain tuning ---------------------------------------------------------------------
WIND_METRIC = env("WIND_METRIC", "sustained")  # "sustained" (10 m wind) or "gust"
TRUCK_DURATION_MULTIPLIER = float(env("TRUCK_DURATION_MULTIPLIER", "1.15"))
WEATHER_GRID_DEG = float(env("WEATHER_GRID_DEG", "0.05"))
WEATHER_CACHE_TTL_S = int(env("WEATHER_CACHE_TTL_S", "1800"))
HEATMAP_MAX_POINTS = int(env("HEATMAP_MAX_POINTS", "240"))
HEATMAP_CORRIDOR_HALF_WIDTH_MILES = float(env("HEATMAP_CORRIDOR_HALF_WIDTH_MILES", "15"))

# Vercel's filesystem is read-only, so log to stdout only.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}