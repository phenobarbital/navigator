#!/usr/bin/env bash
sudo apt-get install libmemcached-dev zlib1g-dev
# first: adding submodules
git submodule add git@bitbucket.org:mobileinsight1/asyncdb.git
git submodule init
git submodule update --init --recursive --remote
