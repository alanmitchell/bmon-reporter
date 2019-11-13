"""Module to create the the HTML reports using Jupyter Notebooks as
the processing logic and final display.
"""

import sys
import logging
import tempfile
from path import Path
from urllib.parse import urlparse

import boto3
import papermill       # installed with: pip install papermill[s3], to include S3 IO features.
import scrapbook       # install with: pip install nteract-scrapbook[s3], just in case S3 features used.

from bmonreporter.file_util import copy_dir_tree
import bmonreporter.config_logging

def create_reports(
    template_path,      
    output_path,
    bmon_urls,
    log_level,
    log_file_path='bmon-reporter-logs/',
    ):
    """Creates all of the reports for Organizations a Buildings across all specified BMON
    servers.

    Input Parameters:

    template_path: directory or S3 bucket + prefix where notebook report templates 
        are stored.  Specify an S3 bucket and prefix by:  s3://bucket/prefix-to-templates
    output_path: directory or S3 bucket + prefix where created reports are stored.
    bmon_urls: a list or iterable containing the base BMON Server URLs that should be 
        processed for creating reports.  e.g. ['https://bms.ahfc.us', 'https://bmon.analysisnorth.com']
    log_file_path: directory or S3 bucket + prefix to store log files from report
        creation; defaults to 'bmon-report-logs' in current directory.
    """

    print(f'''template: {template_path}
output: {output_path}
BMON URLs: {bmon_urls}
Log Level: {log_level}
Log File: {log_file_path}''')

    # set up logging
    # temporary directory for log files
    log_dir = tempfile.TemporaryDirectory()
    bmonreporter.config_logging.configure_logging(
        logging, 
        Path(log_dir.name) / 'bmonreporter.log', 
        log_level
    )

    try:
        # temporary directory for report templates
        templ_dir = tempfile.TemporaryDirectory()
        print(templ_dir.name)
        # copy the report templates into this directory
        copy_dir_tree(template_path, templ_dir.name)

        # Loop through the BMON servers to process
        for server_url in bmon_urls:
            try:
                # create a temporary directory to write reports
                report_dir = tempfile.TemporaryDirectory()
                with open(Path(report_dir.name) / 'test.html', 'w') as fout:
                    fout.write('hello')

            except:
                logging.exception(f'Error processing server {server_url}')

            finally:
                # copy the report files to their final location
                copy_dir_tree(
                    report_dir.name, 
                    str(Path(output_path) / urlparse(server_url).netloc)
                )

    except:
        logging.exception('Error setting up reporter.')

    finally:
        # copy the temporary logging directory to its final location
        copy_dir_tree(log_dir.name, log_file_path)
