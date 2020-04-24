# See: https://packaging.python.org/tutorials/packaging-projects/
# for how to install this package on PyPi.

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

# read version number from package
import bmonreporter
ver = bmonreporter.__version__

setuptools.setup(
    name="bmonreporter",
    version=ver,
    author="Alan Mitchell",
    author_email="tabb99@gmail.com",
    description="Creates Energy Reports from BMON Servers.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/alanmitchell/bmonreporter",
    packages=setuptools.find_packages(),
    scripts=['bin/bmonreporter'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=[
        'pyyaml>=5.1.1',
        'awscli>=1.16.264',
        'boto3>=1.10.0',
        'papermill>=1.2.0',
        'nteract-scrapbook>=0.3.1',
        'bmondata>=1.0.2',
        'plotly>=4.6.0',
        'jupyterthemes>=0.20.0',
    ]
)