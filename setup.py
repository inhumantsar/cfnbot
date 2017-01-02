#!/usr/bin/env python
import os
import sys
from pip.req import parse_requirements
from setuptools import setup

install_reqs = parse_requirements('requirements.txt', session=False)
reqs = [str(i.req) for i in install_reqs]

with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'VERSION.txt')) as version_file:
    version = version_file.read().strip()

setup(
    name='cfnbot',
    version = version,
    description='Makes handling multi-stack deployments to CloudFormation a bit easier',
    long_description=open('README.md').read(),
    author='Shaun Martin',
    author_email='shaun@samsite.ca',
    url='https://github.com/inhumantsar/cfnbot',
    packages=['cfnbot'],
    install_requires=reqs,
    license=open('LICENSE').read(),
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Libraries',
        'Topic :: System :: Distributed Computing',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points = '''
        [console_scripts]
        cfnbot=cfnbot:cli.cli
    ''',
)
