#!/usr/bin/env bash
sudo apt-get install libmemcached-dev zlib1g-dev
# updating pip
pip install --upgrade pip
# first: install framework
python setup.py develop
# second: adding submodules
mkdir extensions
cd extensions
git submodule add git@github.com:phenobarbital/asyncdb.git
git submodule init
git submodule update --init --recursive --remote
# installing
pip install -e asyncdb
# installing asyncdb requirements
pip install --use-feature=2020-resolver -r asyncdb/requirements.txt
# later: post-requirements of Navigator-API
