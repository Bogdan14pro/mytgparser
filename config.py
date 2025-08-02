import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "введи свое да")
#проверь ща, чо с редисом, запусти его
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 5))

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

INVITE_DELAY_SEC = 2
MAX_CONCURRENT_SCRAPING_TASKS = 3
MAX_MSG_LIMIT = 10000
MAX_USER_LIMIT = 5000
AUTH_TIMEOUT_SEC = 300

ADMIN_IDS_ENV = os.getenv("ADMIN_IDS")
if ADMIN_IDS_ENV:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_ENV.split(',') if x.strip().isdigit()]
else:
    ADMIN_IDS = [айдишник введи свой] #getusersid тг бот есть или чет типа такого
