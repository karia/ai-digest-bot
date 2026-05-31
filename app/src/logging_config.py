import logging

from src import config

# Third-party libraries that are too noisy at DEBUG; pinned to WARNING so that
# turning the app up to DEBUG stays readable.
_NOISY_LIBRARIES = ("botocore", "boto3", "urllib3", "s3transfer")


def configure_logging() -> None:
    """Apply the log level from config to the root logger.

    Called at the start of the Lambda handler. The AWS Lambda runtime installs
    a handler on the root logger but leaves its level high, so INFO logs are
    dropped unless we lower both the logger and its handler level here.
    """
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
