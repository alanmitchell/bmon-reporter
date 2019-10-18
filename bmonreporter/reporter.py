"""Module to create the the HTML reports using Jupyter Notebooks as
the processing logic and final display.
"""

import boto3
import papermill       # installed with: pip install papermill[s3], to include S3 IO features.
import scrapbook       # install with: pip install nteract-scrapbook[s3], just in case S3 features used.

def create_reports(
    template_path,      
    output_path,
    bmon_urls,
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
