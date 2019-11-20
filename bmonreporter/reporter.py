"""Module to create the the HTML reports using Jupyter Notebooks as
the processing logic and final display.
"""

import sys
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
import subprocess

import boto3
import papermill as pm       # installed with: pip install papermill[s3], to include S3 IO features.
import scrapbook as sb       # install with: pip install nteract-scrapbook[s3], just in case S3 features used.
import bmondata

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
        # copy the report templates into this directory
        copy_dir_tree(template_path, templ_dir.name)

        # create a temporary directory for scratch purposes, and make a couple file
        # names inside that directory
        scratch_dir = tempfile.TemporaryDirectory()
        out_nb_path = Path(scratch_dir) / 'report.ipynb'
        out_html_path = Path(scratch_dir) / 'report.html'

        # Loop through the BMON servers to process
        for server_url in bmon_urls:
            try:
                logging.info(f'Processing started for {server_url}')

                # create a temporary directory to write reports
                rpt_path = Path(tempfile.TemporaryDirectory())
                
                # loop through all the buildings of the BMON site, running the building
                # templates on each.
                server = bmondata.Server(server_url)
                for bldg in server.buildings():
                    
                    # get the ID for this building
                    bldg_id = bldg['id']

                    # loop through all the building reports and run them on this building.
                    for rpt_nb_path in (Path(templ_dir) / 'building').glob('*.ipynb'):

                        try:
                            pm.execute_notebook(
                                str(rpt_nb_path),
                                str(out_nb_path),
                                parameters = dict(server_web_address=server_url, building_id=bldg_id)
                            )

                            # get the glued scraps from the notebook
                            nb = sb.read_notebook(out_nb_path)
                            scraps = nb.scraps.data_dict()

                            if 'hide' in scraps and scraps['hide'] == True:
                                # report is not available, probably due to lack of data
                                continue

                            # convert the notebook to html. throw an error if one occurs.
                            subprocess.run(f'jupyter nbconvert {out_nb_path} --no-input', shell=True, check=True)

                            # move the resulting html report to the report directory
                            # first create the destination file name
                            dest_name = Path(rpt_nb_path.name).with_suffix('.html')
                            out_html_path.replace(rpt_path / 'building' / str(bldg_id) / dest_name )

                        except:
                            logging.exception(f'Error processing server={server_url}, building={bldg_id}, report={rpt_nb_path.name}')

            except:
                logging.exception(f'Error processing server {server_url}')

            finally:
                # copy the report files to their final location
                copy_dir_tree(
                    str(rpt_path), 
                    str(Path(output_path) / urlparse(server_url).netloc)
                )

    except:
        logging.exception('Error setting up reporter.')

    finally:
        # copy the temporary logging directory to its final location
        copy_dir_tree(log_dir.name, log_file_path)
