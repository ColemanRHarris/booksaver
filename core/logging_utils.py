"""
Context-aware logging utility for Flask and Celery compatibility.
Provides safe logging that works in both Flask app context and standalone Celery workers.
"""

import logging
import os
from typing import Optional


def get_context_aware_logger(name: str) -> logging.Logger:
    """
    Get a logger that works in both Flask and Celery contexts.
    Falls back to standalone logging when Flask context is unavailable.
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(name)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Set log level based on environment
        log_level = logging.INFO if os.getenv('FLASK_ENV') == 'production' else logging.DEBUG
        logger.setLevel(log_level)
        
        # Prevent duplicate logs from parent loggers
        logger.propagate = False
    
    return logger


class ContextAwareLogger:
    """
    Logger wrapper that safely handles both Flask and Celery contexts.
    Automatically falls back to standalone logging when Flask context unavailable.
    """
    
    def __init__(self, name: str):
        self.name = name
        self._standalone_logger = get_context_aware_logger(name)
        
    def _get_logger(self):
        """Get the appropriate logger for the current context."""
        try:
            # Try to use Flask's current_app.logger if available
            from flask import current_app
            if current_app:
                return current_app.logger
        except (ImportError, RuntimeError):
            # ImportError: Flask not available
            # RuntimeError: Working outside of application context
            pass
        
        # Fall back to standalone logger
        return self._standalone_logger
    
    def debug(self, message: str):
        """Log debug message."""
        self._get_logger().debug(message)
    
    def info(self, message: str):
        """Log info message."""
        self._get_logger().info(message)
    
    def warning(self, message: str):
        """Log warning message."""
        self._get_logger().warning(message)
    
    def error(self, message: str):
        """Log error message."""
        self._get_logger().error(message)
    
    def critical(self, message: str):
        """Log critical message."""
        self._get_logger().critical(message)
    
    def log(self, level: int, message: str):
        """Log message at specified level."""
        self._get_logger().log(level, message)


def get_safe_logger(name: str) -> ContextAwareLogger:
    """
    Get a context-aware logger instance.
    
    Usage:
        logger = get_safe_logger(__name__)
        logger.info("This works in both Flask and Celery contexts")
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        ContextAwareLogger instance
    """
    return ContextAwareLogger(name)


# Convenience function for backward compatibility
def create_safe_logger(name: str) -> ContextAwareLogger:
    """
    Create a safe logger (alias for get_safe_logger).
    """
    return get_safe_logger(name)