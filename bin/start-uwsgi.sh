#!/bin/bash

export PYENV_ROOT="/home/isucon/.pyenv"
export PATH="$PYENV_ROOT/bin:/home/isucon/lib:$PATH"
export LC_ALL="en_US.UTF-8"
export ISUCONP_DB_NAME="isuconp"
/home/isucon/.pyenv/shims/uwsgi /home/isucon/etc/uwsgi.ini
