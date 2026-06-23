import logging
import os


logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("fancy_logger").setLevel(logging.ERROR)
logging.getLogger("ai_atlas_nexus").setLevel(logging.WARNING)
logging.getLogger("faiss.loader").setLevel(logging.ERROR)
logging.getLogger("cpex.framework.manager").setLevel(logging.ERROR)
os.environ["MELLEA_LOG_LEVEL"] = "ERROR"

# ANSI color codes
COLORS = {
    "DEBUG": "\033[36m",  # Cyan
    "INFO": "\033[32m",  # Green
    "WARNING": "\033[33m",  # Yellow
    "ERROR": "\033[31m",  # Red
    "RESET": "\033[0m",  # Reset
}


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        log_color = COLORS.get(record.levelname, COLORS["RESET"])
        record.levelname = f"{log_color}{record.levelname}{COLORS['RESET']}"
        return super().format(record)


def configure_logger(name: str = "MelleaSkills"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)

    handler.setFormatter(
        ColoredFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%d-%m-%Y %H:%M:%S",
        )
    )
    logger.handlers = [handler]

    return logger
