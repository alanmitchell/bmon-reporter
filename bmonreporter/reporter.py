"""Module to create the the HTML reports using Jupyter Notebooks as
the processing logic and final display.
"""

import sys
import logging
import tempfile
from pathlib import Path
import shutil
from urllib.parse import urlparse
import subprocess
from typing import Iterable
from multiprocessing import Pool
from functools import partial
import pickle
import json
import yaml

import papermill as pm       # installed with: pip install papermill[s3], to include S3 IO features.
import scrapbook as sb       # install with: pip install nteract-scrapbook[s3], just in case S3 features used.
import bmondata

from bmonreporter.file_util import copy_dir_tree
import bmonreporter.config_logging

def create_reports(
        source_repos,
        log_level,
        log_file_dir='bmon-reporter-logs/',
        cores=1,
    ):
    """Creates all of the reports for Organizations a Buildings across all specified BMON
    servers.

    Input Parameters:

    source_repos: a list of dictionaries, one dictionary for each GitHub repository containing
        notebook report templates and configuration info.  The dictionary must have a 'git_spec'
        key indicating the GitHub spec used to clone the repo, 
        eg. git@github.com:alanmitchell/bmonreporter-templates.git.  A 'branch' key is optional
        indicating which branch of the repo to use; if the 'branch' key of the dictionary is not
        present, the 'master' branch is used.
    log_level: string indicating detail of logging to occur: DEBUG, INFO, WARNING, ERROR
    log_file_dir: (optional) directory or S3 bucket + prefix to store log files from report
        creation; defaults to 'bmon-report-logs' in current directory.
    cores: (optional) # of cores available to process this script.  Defaults to 1.
    """

    try:
        # Set up a main temporary directory, which will have a folder for logs.
        # ├── bmonreporter_<temp directory id>
        #     ├── logs            # log files
        temp_dir = tempfile.TemporaryDirectory(prefix='bmonreporter_')
        temp_dir_path = Path(temp_dir.name)
        (temp_dir_path / 'logs').mkdir()

        # set up logging
        bmonreporter.config_logging.configure_logging(
            logging, 
            temp_dir_path / 'logs/bmonreporter.log', 
            log_level
        )

        try:

            # Loop through the Git repos to process, but use the multiprocessing
            # module to do this in multiple processes.
            cores_to_use = min(len(source_repos), cores)
            with Pool(cores_to_use) as p:
                p.map(process_repo, source_repos)
            
        except:
            logging.exception('Error setting up reporter.')
            
    finally:
        # copy the temporary logging directory to its final location
        try:
            copy_dir_tree(str(temp_dir_path / 'logs'), log_file_dir, 'text/plain; charset=ISO-8859-15')
        except:
            logging.exception('Error uploading logging directory.')
        
        # Clean up the main temporary directory
        temp_dir.cleanup()

def process_repo(git_info: dict):
    """Processes one GitHub repo containing notebook report templates and configuration info
    indicating which servers the reports should be applied to, what Jupyter theme to use, and
    where to store the final reports.
    'git_info' is a dictionary with at least a 'git_spec' key that gives the address that 
    should be given to 'git clone' to clone the repo.  A second, optional, key is 'branch'
    which gives the repo branch to use.  If that key is not present, the 'master' branch
    is used.
    """
    try:
        # make a temporary directory to clone the repo into.
        repo_dir = tempfile.TemporaryDirectory(prefix=f'repo_')
        repo_path = Path(repo_dir.name)

        # clone the repo into this directory.
        git_spec = git_info['git_spec']
        git_branch = git_info.get('branch', 'master')   # default to master branch.
        subprocess.run(f'git clone -b {git_branch} --depth 1 {git_spec} {repo_dir.name}', shell=True, check=True)

        # read the contents of the YAML configuration file in the root of the repo.
        config = yaml.load(open(repo_path / 'config.yaml'), Loader=yaml.SafeLoader)

        # execute the Jupyter theme command found in the config file. This will format the
        # notebooks as desired by the user.
        subprocess.run(config['jup_theme_cmd'], shell=True, check=True)

        # get the output directory or S3 bucket/key from the config file.
        output_dir = config['output_dir']

        # make a Path object pointing to the template directory in the repo
        template_path = repo_path / 'templates'

        # loop through the BMON servers that are targeted by this repo and process
        for server_url in config['bmon_urls']:
            process_server(server_url, template_path, output_dir) 

    except:
        logging.exception(f'Error processing Git repo {git_info}')

    finally:
        # remove the temporary directory
        repo_dir.cleanup()

def process_server(server_url: str, template_path: Path, output_dir: str):
    """Create the reports for one BMON server with the base URL of 'server_url'.
    'template_path' is the Path to the Jupyter templates
    Copy the reports to the directory specified by 'output_dir', placed in a
    subdirectory named after the server_url.
    """

    try:
        # extract server domain for message labeling purposes
        server_domain = server_url  # in case next statement errors, we have something to log
        server_domain = urlparse(server_url).netloc

        logging.info(f'Processing started for {server_domain}')

        # Make a working directory and a reports directory for this server
        server_dir = tempfile.TemporaryDirectory(prefix=f'bm_{urlparse(server_url).netloc}_')
        server_path = Path(server_dir.name)
        rpt_path = server_path / 'reports'
        rpt_path.mkdir()
        working_path = server_path / 'working'
        working_path.mkdir()

        # loop through all the buildings of the BMON site, running the building
        # templates on each.
        server = bmondata.Server(server_url)
        bldgs = server.buildings()     # all buildings
        bldg_ids = [bldg['id'] for bldg in bldgs]
        bldg_rpt_dict = run_report_set(
            server_url,
            'building_id',
            bldg_ids,
            working_path,
            template_path / 'building',
            rpt_path / 'building',
            )
        # save the report dictionary into a pickle file and a JSON file
        pickle.dump(bldg_rpt_dict, open(rpt_path / 'building.pkl', 'wb'))
        json.dump(bldg_rpt_dict, open(rpt_path / 'building.json', 'w'))

        # List of the organization IDs including ID = 0 for all organizations.
        orgs = server.organizations()     # all organizations
        org_ids = [0] + [org['id'] for org in orgs]
        org_rpt_dict = run_report_set(
           server_url,
           'org_id',
           org_ids,
           working_path,
           template_path / 'organization',
           rpt_path / 'organization',
           )
        # save the report dictionary into a pickle file and a JSON file.
        pickle.dump(org_rpt_dict, open(rpt_path / 'organization.pkl', 'wb'))
        json.dump(org_rpt_dict, open(rpt_path / 'organization.json', 'w'))

        # Add some additional files that give full list of organizations and a 
        # mapping between each organization and the buildings associated with it.
        # This info will allow someone to build a report viewing application 
        # without having to make any API calls to the BMON server directly.  Also,
        # this information will be time-consistent with the generated reports.

        # Title and ID of every organization, including ID = 0, which represents
        # all organizations.
        all_orgs = [('All Organizations', 0)] + [(org['title'], org['id']) for org in orgs]
        pickle.dump(all_orgs, open(rpt_path / 'all_orgs.pkl', 'wb'))
        json.dump(all_orgs, open(rpt_path / 'all_orgs.json', 'w'))

        # Dictionary mapping an Organization to a list of Buildings, each building
        # having a title and an ID.  Organization 0 maps to all buildings.
        org_to_bldgs = {0: [(bldg['title'], bldg['id']) for bldg in bldgs]}
        for org in orgs:
            org_to_bldgs[org['id']] =  [(bldg[1], bldg[0]) for bldg in org['buildings']]
        pickle.dump(org_to_bldgs, open(rpt_path / 'org_to_bldgs.pkl', 'wb'))
        json.dump(org_to_bldgs, open(rpt_path / 'org_to_bldgs.json', 'w'))

    except:
        logging.exception(f'Error processing server {server_domain}')

    finally:
        try:
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

        except:
            logging.exception(f'Error copying report files to final destination, {server_domain}.')

        server_dir.cleanup()

def run_report_set(
        server_url: str,
        param_name: str,
        param_values: Iterable,
        working_path: Path,
        nb_template_path: Path,
        rpt_output_path: Path,
    ):
    """Creates a set of reports by cycling through a set of buildings or organizations
    and then cycling through a set of Jupyter notebook templates used to create the reports.
    Input Parameters:
        server_url: the full URL to BMON server that holds the data
        param_name: the name of building or organization parameter in the notebook template
        param_values: a list of values to cycle through for the notebook parameter.
        working_path: the Path to a working directory for use by this routine
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

    # Make file names for the calculate notebook being currently run and 
    # the HTML report that is created from that template.
    out_nb_path = working_path / 'report.ipynb'
    out_html_path = working_path / 'report.html'

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