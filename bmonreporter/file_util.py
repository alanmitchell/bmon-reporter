"""Utilities to facilitate copying files and directories where one of the directories
could possibly be an S3 bucket.
This module requires that the AWS CLI is installed because "aws s3 sync" is used.
"""
import shutil
from pathlib import Path
import subprocess

def copy_dir_tree(from_dir, to_dir, content_type=None):
    """Recursively copies a directory to another location, deleting any files
    at that location that are not in the source directory.  'from_dir' and 'to_dir'
    directories can be S3 buckets + key prefix.
    If 'content_type' is not None, then the content-type of the files will be
    explicitly set to the passed in value.
    """
    # determine whether from and to directories are S3 directories
    from_is_s3 = (from_dir[:5] == 's3://')
    to_is_s3 = (to_dir[:5] == 's3://')
    
    # If neither directories are on S3, use a coventional copy tree command.
    # This will error if 'to_dir' exists, so first remove it if it is present.
    if from_is_s3 or to_is_s3:
        # use the AWS CLI S3 sync command.  Delete any destination files that
        # do not exist in the source.
        if content_type:
            subprocess.run(['aws', 's3', 'sync', from_dir, to_dir, '--delete', '--content-type', content_type])
        else:
            subprocess.run(['aws', 's3', 'sync', from_dir, to_dir, '--delete'])
    else:
        if Path(to_dir).exists():
            shutil.rmtree(to_dir)
        shutil.copytree(from_dir, to_dir)
