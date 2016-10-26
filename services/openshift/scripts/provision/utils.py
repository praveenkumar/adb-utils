#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import subprocess
import sys

# Enable Logging
logger = logging.getLogger("openshift")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - \
                                      %(message)s")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger.addHandler(handler)

ORIGIN_DIR = "/var/lib/openshift"
OPENSHIFT_DIR = "%s/openshift.local.config/master" % ORIGIN_DIR
OPENSHIFT_SUBDOMAIN = subprocess.check_output(
        'eval "OPENSHIFT_SUBDOMAIN=${OPENSHIFT_SUBDOMAIN}" && echo $OPENSHIFT_SUBDOMAIN', shell=True)

def system(cmd):
    """
    Runs a shell command, and returns the output, err, returncode
    :param cmd: The command to run.
    :return:  Tuple with (output, err, returncode).
    """
    ret = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    out, err = ret.communicate()
    returncode = ret.returncode
    return out, err, returncode

def log_error(msg):
    logger.error(msg)
    sys.exit(1)
