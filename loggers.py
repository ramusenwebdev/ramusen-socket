import logging
import os

# Configure logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# File log for application and Asterisk
app_log_filename = os.path.join(log_dir, 'application.log')
asterisk_log_filename = os.path.join(log_dir, 'asterisk.log')

# Logger for application
app_logger = logging.getLogger('application')
app_logger.setLevel(logging.DEBUG)
app_file_handler = logging.FileHandler(app_log_filename)
app_stream_handler = logging.StreamHandler()
app_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
app_file_handler.setFormatter(app_formatter)
app_stream_handler.setFormatter(app_formatter)
app_logger.addHandler(app_file_handler)
app_logger.addHandler(app_stream_handler)

# Logger for Asterisk
asterisk_logger = logging.getLogger('asterisk')
asterisk_logger.setLevel(logging.DEBUG)
asterisk_file_handler = logging.FileHandler(asterisk_log_filename)
asterisk_stream_handler = logging.StreamHandler()
asterisk_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
asterisk_file_handler.setFormatter(asterisk_formatter)
asterisk_stream_handler.setFormatter(asterisk_formatter)
asterisk_logger.addHandler(asterisk_file_handler)
asterisk_logger.addHandler(asterisk_stream_handler)
