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
        out_nb_path = Path(scratch_dir.name) / 'report.ipynb'
        out_html_path = Path(scratch_dir.name) / 'report.html'

        # Loop through the BMON servers to process
        for server_url in bmon_urls:
            try:
                logging.info(f'Processing started for {server_url}')

                # create a temporary directory to write reports
                rpt_dir = tempfile.TemporaryDirectory()
                rpt_path = Path(rpt_dir.name)
                
                # loop through all the buildings of the BMON site, running the building
                # templates on each.
                server = bmondata.Server(server_url)
                for bldg in server.buildings():
                    
                    # get the ID for this building
                    bldg_id = bldg['id']

                    if bldg_id != 2:
                        continue

                    # loop through all the building reports and run them on this building.
                    for rpt_nb_path in (Path(templ_dir.name) / 'building').glob('*.ipynb'):

                        try:
                            pm.execute_notebook(
                                str(rpt_nb_path),
                                str(out_nb_path),
                                parameters = dict(server_web_address=server_url, building_id=bldg_id),
                                kernel_name='python3',
                            )
                            print('finished nb execution')
                            # get the glued scraps from the notebook
                            nb = sb.read_notebook(str(out_nb_path))
                            scraps = nb.scraps.data_dict

                            if 'hide' in scraps and scraps['hide'] == True:
                                # report is not available, probably due to lack of data
                                continue

                            # convert the notebook to html. throw an error if one occurs.
                            subprocess.run(f'jupyter nbconvert {out_nb_path} --no-input', shell=True, check=True)

                            # move the resulting html report to the report directory
                            # first create the destination file name and create the necessary
                            # directories, if they don't exist.
                            dest_name = Path(rpt_nb_path.name).with_suffix('.html')
                            dest_path = rpt_path / 'building' / str(bldg_id) / dest_name
                            dest_path.parent.mkdir(parents=True, exist_ok=True)
                            out_html_path.replace(dest_path)

                        except pm.PapermillExecutionError as err:
                            if err.ename == 'RuntimeError':
                                # This error was raised intentionally to stop notebook execution.
                                # Just log an info message.
                                logging.info(f'Report aborted for server={server_url}, building={bldg_id}, report={rpt_nb_path.name}: {err.evalue}')
                            else:
                                logging.exception(f'Error processing server={server_url}, building={bldg_id}, report={rpt_nb_path.name}')

                        except:
                            logging.exception(f'Error processing server={server_url}, building={bldg_id}, report={rpt_nb_path.name}')

                    if bldg_id==2:
                        break

            except:
                logging.exception(f'Error processing server {server_url}')

            finally:
                # copy the report files to their final location
                dest_dir = str(Path(output_path) / urlparse(server_url).netloc)

                # If the destination is s3, the Path concatenation above stripped out a /
                # that needs to be put back in.
                if dest_dir.startswith('s3:'):
                    dest_dir = 's3://' + dest_dir[4:]
                
                copy_dir_tree(
                    str(rpt_path), 
                    dest_dir
                )

            break

    except:
        logging.exception('Error setting up reporter.')

    finally:
        # copy the temporary logging directory to its final location
        copy_dir_tree(log_dir.name, log_file_path)

def test():
    """Run the example configuration file as a test case.
    """
    import yaml
    config_file_path = '/home/tabb99/bmonreporter/bmonreporter/config_example.yaml'
    args = yaml.load(open(config_file_path), Loader=yaml.SafeLoader)
    create_reports(**args)

if __name__ == "__main__":
    test()