import os

BEETSDIR = os.environ.get("BEETSDIR", "/config")
BEETS_DB_PATH = os.path.join(BEETSDIR, "musiclibrary.db")

SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/scripts")
IMPORT_QUEUE_DIR = os.path.join(SCRIPTS_DIR, "import-queue")
IMPORT_FAILED_LOG = os.path.join(SCRIPTS_DIR, "import-failed.log")
IMPORT_FAILED_DISMISSED_LOG = os.path.join(SCRIPTS_DIR, "import-failed-dismissed.log")
ON_COMPLETE_LOG = os.path.join(SCRIPTS_DIR, "on-complete.log")
LOCK_FILE = os.path.join(SCRIPTS_DIR, "manual-match.lock")
IMPORT_ACTIVE_FILE = os.path.join(SCRIPTS_DIR, "import-active")
WISHLIST_FILE = os.path.join(SCRIPTS_DIR, "wishlist.json")

MB_CONTACT = os.environ.get("MB_CONTACT", "music-manager@localhost")
MB_USER_AGENT = f"music-manager/1.0 ( {MB_CONTACT} )"

MUSIC_LIBRARY_DIR = os.environ.get("MUSIC_LIBRARY_DIR", "/media/music")
IMPORT_BASE_DIR = os.environ.get("IMPORT_BASE_DIR", "/media/downloads/complete/music")
IMPORT_STAGE_DIR = os.environ.get("IMPORT_STAGE_DIR", "/media/import-stage")
