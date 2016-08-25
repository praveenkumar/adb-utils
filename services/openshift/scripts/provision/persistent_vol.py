#!/usr/bin/env python
# -*- coding: utf-8 -*-

import grp
import json
import logging
import os
import pwd
import subprocess
import sys
import time
import tempfile
from argparse import ArgumentParser
from utils import ORIGIN_DIR, OPENSHIFT_DIR, OPENSHIFT_SUBDOMAIN
from utils import logger, system, log_error

os.environ['KUBECONFIG'] = "%s/admin.kubeconfig" % OPENSHIFT_DIR
NFS_Dir = '/nfsnobody'

PV_TEMPLATE = """apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv{0}
spec:
  capacity:
    storage: {1}Gi
  accessModes:
    - ReadWriteOnce
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Recycle
  nfs:
    server: localhost
    path: /nfsvolumes/pv{0}"""

def configure_nfs():
    logger.info("Configuring NFS")
    subprocess.call("setsebool -P virt_use_nfs 1", shell=True)
    subprocess.call("systemctl start nfs-server", shell=True)
    subprocess.call("systemctl enable nfs-server", shell=True)

def list_pv(path):
    return len(os.listdir(path))

def create_dir(path):
    os.makedirs(path)
    uid = pwd.getpwnam("nfsnobody").pw_uid
    gid = grp.getgrnam("nfsnobody").gr_gid
    os.chown(path, uid, gid)
    os.chmod(path, 0777)

def update_exports(path):
    if not os.path.isfile('/etc/exports'):
        os.makedirs('/etc/exports', mode=0644)
    with open('/etc/exports', 'a') as fh:
        fh.write("%s *(rw,root_squash)\n" % path)

def persistent_vol_setup(pv_number=3, pv_capacity=1):
    logger.info("Creating persistent volumes")
    if not os.path.isdir(NFS_Dir):
        try:
            create_dir(NFS_Dir)
        except OSError as err:
            logger.error(err)
    pv_list = list_pv(NFS_Dir)
    for pv in range(pv_list, pv_list+pv_number):
        logger.info("Creating required directories")
        create_dir('%s/pv%s' % (NFS_Dir, pv))
        update_exports('%s/pv%s' % (NFS_Dir, pv))
        if subprocess.call("systemctl restart nfs-server", shell=True):
            logger.error("NFS server restart failed")
        vol_template = PV_TEMPLATE.format(pv, pv_capacity)
        file_discriptor, temp_file = tempfile.mkstemp(text=True)
        with open(temp_file, 'w') as fh:
            fh.write(vol_template)
        if subprocess.call('oc create -f %s' % temp_file ,shell=True):
            os.unlink(temp_file)
            log_error("Failed to create nfs mount")
        os.unlink(temp_file)

def main():
    configure_nfs()
    persistent_vol_setup()

if __name__ == '__main__':
    main()
