import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(log_dir="logs", log_file="ariadne.log", level=logging.INFO):
    """
    Configures the logging system for Ariadne.
    
    Args:
        log_dir (str): Directory to store log files.
        log_file (str): Name of the log file.
        level (int): Logging level (default: logging.INFO).
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    log_path = os.path.join(log_dir, log_file)
    
    # Create formatters
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '[%(asctime)s] %(message)s', # Simpler for console
        datefmt='%H:%M:%S'
    )
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear existing handlers to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    
    # File Handler (Rotating)
    file_handler = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(level)
    root_logger.addHandler(file_handler)
    
    # Console Handler (Optional: user interface usually handles printing, but we can log errors here)
    # We might want to keep console clean and rely on print() in UI, but log everything to file.
    # For now, let's strictly log to file to avoid double printing in the chat UI.
    # If the user wants to see logs in the console, we can add this back or use a separate logger.
    
    # However, user requested "I want to see at what time a tool is called...". 
    # My previous change added print() to tools. I will convert those to logs 
    # and maybe add a specific console handler for "Tool" events if desired.
    # But for simplicity, I'll stick to file logging for persistence and let the UI handle display.
    
    logging.info("Logging initialized.")
