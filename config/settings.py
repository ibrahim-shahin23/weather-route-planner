"""Settings. Everything deploy-specific comes from environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
if env("RENDER_EXTERNAL_HOSTNAME"):  # set automatically on Render
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "apps.trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
USE_TZ = True
TIME_ZONE = "UTC"
DATABASES: dict = {}  # stateless: no database needed
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- CORS / proxy ------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Static SPA (built React app) served by WhiteNoise -----------------------
FRONTEND_DIST = Path(env("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist")))
if FRONTEND_DIST.exists():
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True

# --- Cache (weather + geocoding). Use Redis in production for shared state. ---
REDIS_URL = env("REDIS_URL")
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
if env("NUM_PROXIES"):
    REST_FRAMEWORK["NUM_PROXIES"] = int(env("NUM_PROXIES"))

# --- Third-party services --------------------------------------------------------
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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
