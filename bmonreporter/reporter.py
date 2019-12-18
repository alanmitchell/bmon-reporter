"""Module to create the the HTML reports using Jupyter Notebooks as
the processing logic and final display.
"""

import sys
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
import subprocess
from typing import Iterable
from multiprocessing import Pool
from functools import partial
import pickle

import boto3
import papermill as pm       # installed with: pip install papermill[s3], to include S3 IO features.
import scrapbook as sb       # install with: pip install nteract-scrapbook[s3], just in case S3 features used.
import bmondata

from bmonreporter.file_util import copy_dir_tree
import bmonreporter.config_logging

def create_reports(
        template_dir,      
        output_dir,
        bmon_urls,
        jup_theme_cmd,
        log_level,
        log_file_dir='bmon-reporter-logs/',
        cores=1,
    ):
    """Creates all of the reports for Organizations a Buildings across all specified BMON
    servers.

    Input Parameters:

    template_dir: directory or S3 bucket + prefix where notebook report templates 
        are stored.  Specify an S3 bucket and prefix by:  s3://bucket/prefix-to-templates
    output_dir: directory or S3 bucket + prefix where created reports are stored.
    bmon_urls: a list or iterable containing the base BMON Server URLs that should be 
        processed for creating reports.  e.g. ['https://bms.ahfc.us', 'https://bmon.analysisnorth.com']
    jup_theme_cmd: this is the Jupyter Theme command to run prior to generating reports.  This will
        set the formatting of the notebooks.  See: https://github.com/dunovank/jupyter-themes
    log_level: string indicating detail of logging to occur: DEBUG, INFO, WARNING, ERROR
    log_file_dir: (optional) directory or S3 bucket + prefix to store log files from report
        creation; defaults to 'bmon-report-logs' in current directory.
    cores: (optional) # of cores available to process this script.  Defaults to 1.
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
        # Run the Jupyter Themes command to get correct formatting of the notebook reports.
        subprocess.run(jup_theme_cmd, shell=True, check=True)

        # temporary directory for report templates
        templ_dir = tempfile.TemporaryDirectory()
        # copy the report templates into this directory
        copy_dir_tree(template_dir, templ_dir.name)

        # Loop through the BMON servers to process, but use the multiprocessing
        # module to do this in multiple processes.  To use multriprocessing you 
        # need to have a function with one parameter; create that with
        # functools.partial.
        server_func = partial(
            process_server, 
            template_dir=templ_dir.name,
            output_dir=output_dir 
            )
        cores_to_use = min(len(bmon_urls), cores)
        with Pool(cores_to_use) as p:
            p.map(server_func, bmon_urls)
        
    except:
        logging.exception('Error setting up reporter.')

    # copy the temporary logging directory to its final location
    copy_dir_tree(log_dir.name, log_file_dir, 'text/plain; charset=ISO-8859-15')

def process_server(server_url: str, template_dir: str, output_dir: str):
    """Create the reports for one BMON server with the base URL of 'server_url'.
    Pull report template notebooks from the 'template_dir' directory.
    Copy the reports to the directory specificed by 'output_dir', placed in a
    subdirectory named after the server_url.
    """
    # extract server domain for message labeling purposes
    server_domain = urlparse(server_url).netloc

    try:
        logging.info(f'Processing started for {server_domain}')
        
        # create a temporary directory to write reports
        rpt_dir = tempfile.TemporaryDirectory()
        rpt_path = Path(rpt_dir.name)
        
        # loop through all the buildings of the BMON site, running the building
        # templates on each.
        server = bmondata.Server(server_url)
        bldg_ids = [bldg['id'] for bldg in server.buildings()]
        bldg_rpt_dict = run_report_set(
            server_url,
            'building_id',
            bldg_ids,
            Path(template_dir) / 'building',
            rpt_path / 'building',
            )
        # save the report dictionary into a pickle file
        pickle.dump(bldg_rpt_dict, open(rpt_path / 'building.pkl', 'wb'))

        # List of the organization IDs including ID = 0 for all organizations.
        org_ids = [0] + [org['id'] for org in server.organizations()]
        org_rpt_dict = run_report_set(
           server_url,
           'org_id',
           org_ids,
           Path(template_dir) / 'organization',
           rpt_path / 'organization',
           )
        # save the report dictionary into a pickle file
        pickle.dump(org_rpt_dict, open(rpt_path / 'organization.pkl', 'wb'))

    except:
        logging.exception(f'Error processing server {server_domain}')

    # copy the report files to their final location
    dest_dir = str(Path(output_dir) / server_domain)

    # If the destination is s3, the Path concatenation above stripped out a /
    # that needs to be put back in.
    if dest_dir.startswith('s3:'):
        dest_dir = 's3://' + dest_dir[4:]
    
    copy_dir_tree(
        str(rpt_path), 
        dest_dir
    )

def run_report_set(
        server_url: str,
        param_name: str,
        param_values: Iterable,
        nb_template_path: Path,
        rpt_output_path: Path,
    ):
    """Creates a set of reports by cycling through a set of buildings or organizations
    and then cycling through a set of Jupyter notebook templates used to create the reports.
    Input Parameters:
        server_url: the full URL to BMON server that holds the data
        param_name: the name of building or organization parameter in the notebook template
        param_values: a list of values to cycle through for the notebook parameter.
        nb_template_path: a Path to the directory where the template report notebooks are stored.
        rpt_output_path: a Path to the directory where the final HTML reports are stored. A
            subdirectory for each parameter value will be created in this directory to hold all
            the reports for that particular building or organization.

    Returns a dictionary keyed on parameter value that lists the reports for that
    parameter value; each item in the list is a dictionary describing the report.
    """
    # extract server domain for message labeling purposes
    server_domain = urlparse(server_url).netloc

    # Make a dictionary to keep track of the reports created for each parameter
    # value.  Key is paramater value, value is list of report records.  Each report
    # record is a dictionary giving info about the report.
    report_dict = {}

    # create a temporary directory for scratch purposes, and make file
    # names inside that directory for the calculated report notebook and the HTML
    # files that is created from that notebook.
    scratch_dir = tempfile.TemporaryDirectory()
    out_nb_path = Path(scratch_dir.name) / 'report.ipynb'
    out_html_path = Path(scratch_dir.name) / 'report.html'

    # Keep track of how many reports completed and aborted
    completed_ct = 0
    aborted_ct = 0

    # Loop through all the parameter values (e.g. buildings or organizations)
    for param_val in param_values:
        rpts = []   # a list of reports for this parameter value
        for rpt_nb_path in nb_template_path.glob('*.ipynb'):

            try:
                pm.execute_notebook(
                    str(rpt_nb_path),
                    str(out_nb_path),
                    parameters = {'server_web_address': server_url, param_name: param_val},
                    kernel_name='python3',
                )

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
                dest_path = rpt_output_path / str(param_val) / dest_name
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                out_html_path.replace(dest_path)

                # Add to the dictionary of completed reports.
                rpts.append(
                    {
                        'title': scraps['title'],
                        'sort_order': scraps['sort_order'],
                        'file_name': str(dest_name),
                    }
                )
                completed_ct += 1

            except pm.PapermillExecutionError as err:
                aborted_ct += 1
                if err.ename == 'RuntimeError':
                    # This error was raised intentionally to stop notebook execution.
                    # Just log an info message.
                    logging.info(f'Report aborted for server={server_domain}, {param_name}={param_val}, report={rpt_nb_path.name}: {err.evalue}')
                else:
                    logging.exception(f'Error processing server={server_domain}, {param_name}={param_val}, report={rpt_nb_path.name}')

            except:
                aborted_ct += 1
                logging.exception(f'Error processing server={server_domain}, {param_name}={param_val}, report={rpt_nb_path.name}')

        # sort the reports in sort order for this parameter value
        rpts = sorted(rpts, key=lambda r: (r['sort_order'], r['title']))
        # only include if reports are present.
        if rpts:
            report_dict[param_val] = rpts
        
    # log the number of completed and aborted reports
    logging.info(f'For server {server_domain}, report type {param_name}, {completed_ct} reports completed, {aborted_ct} reports aborted.')

    return report_dict

def test():
    """Run the example configuration file as a test case.
    """
    import yaml
    config_file_path = '/home/tabb99/bmonreporter/bmonreporter/config_example.yaml'
    args = yaml.load(open(config_file_path), Loader=yaml.SafeLoader)
    create_reports(**args)

if __name__ == "__main__":
    test()