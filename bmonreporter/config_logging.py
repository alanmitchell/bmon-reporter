"""Module used to configure exception and other application logging.
"""
import logging
import logging.handlers
import sys

def configure_logging(logging_module, log_file_path, log_level):
    """Configures the logging for an application.  Usage example:
           import logging
           import config_logging
           config_logging.configure_logging(logging, '/var/log/logfilename', 'INFO')

       Note that the 'log_level' parameter should be string matching a logging level
       attribute of the logging module: e.g. "INFO" or "DEBUG"
    """

    # Use the root logger for the application.

    # set the log level. Because we are setting this on the logger, it will apply
    # to all handlers (unless maybe you set a specific level on a handler?).
    logging_module.root.setLevel(getattr(logging, log_level))

    # create a rotating file handler
    fh = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=200000, backupCount=5)

    # create formatter and add it to the handler
    formatter = logging_module.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    fh.setFormatter(formatter)

    # filter out some records
    filtr = MyFilter()
    fh.addFilter(filtr)

    # create a handler that will print to console as well.
    console_h = logging_module.StreamHandler()
    console_h.setFormatter(formatter)
    console_h.addFilter(filtr)

    # add the handlers to the root logger
    logging_module.root.addHandler(fh)
    logging_module.root.addHandler(console_h)


class MyFilter(logging.Filter):
    """Class to restrict which logging records get logged.
    """

    def filter(self, record):

        # Don't record the records coming from the papermill execute module
        if record.module == 'execute':
            return False

        return True
