import datetime
import logging
import os

from flask import Flask


def create_app() -> Flask:
    _log = logging.getLogger(__name__)
    app = Flask(__name__)

    from app import config as _cfg

    if not os.path.exists(_cfg.BEETS_DB_PATH):
        _log.warning("Beets database not found at %s — check volume mount", _cfg.BEETS_DB_PATH)

    from app.lock import cleanup_stale_lock

    cleanup_stale_lock()

    from app.routes.browse import bp as browse_bp
    from app.routes.album import bp as album_bp
    from app.routes.failed import bp as failed_bp
    from app.routes.library import bp as library_bp
    from app.routes.manual_match import bp as manual_match_bp
    from app.routes.queue import bp as queue_bp
    from app.routes.remove import bp as remove_bp
    from app.routes.wishlist import bp as wishlist_bp

    app.register_blueprint(browse_bp)
    app.register_blueprint(album_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(remove_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(failed_bp)
    app.register_blueprint(manual_match_bp)
    app.register_blueprint(wishlist_bp)

    @app.template_filter("datetimeformat")
    def datetimeformat(value: int) -> str:
        return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")

    from app import watcher
    watcher.start_watcher()

    return app
