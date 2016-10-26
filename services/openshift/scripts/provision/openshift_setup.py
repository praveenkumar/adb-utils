#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import os
import subprocess
import sys
import time
import tempfile
from argparse import ArgumentParser
from utils import ORIGIN_DIR, OPENSHIFT_DIR, OPENSHIFT_SUBDOMAIN
from utils import system, log_error, logger

os.environ['KUBECONFIG'] = "%s/admin.kubeconfig" % OPENSHIFT_DIR

def wait_for_openshift_api():
    # Wait for OpenShift container to show up
    attempt = 0
    while (system('docker inspect openshift')[2] or attempt == 10):
        time.sleep(1)
        attempt += 1
    if system('docker inspect openshift')[2]:
        log_error("Failed to start OpenShift Container")
    attempt = 0
    while (system('curl -ksSf https://127.0.0.1:8443/healthz/ready')[2] or attempt == 10):
        time.sleep(1)
        attempt += 1
    if system('curl -ksSf https://127.0.0.1:8443/healthz/ready')[2]:
        log_error("OpenShift container is not in good health")


def copy_openshift_client_binaries():
    # Note: oc and oadm are symlinks to openshift
    logger.info("Copying openshift client binaries")
    binaries = ['openshift', 'oc', 'oadm']
    for binary in binaries:
        if not os.path.isfile('/usr/bin/%s' % binary):
            if system('docker cp openshift:/usr/bin/{0} /usr/bin/{0}'.format(binary))[2]:
                log_error("Failed to copy openshift client binary")


def create_docker_registry():
    if not os.path.isfile('%s/registry.configured' % ORIGIN_DIR):
        logger.info("Configuring Docker Registry")
        if system('oadm registry --create --service-account=registry')[2]:
            log_error("Failed to create service account for registry")
        if system('oadm policy add-scc-to-group anyuid system:authenticated')[2]:
            log_error("Failed to add system authenticated policy")
        system('touch %s/registry.configured' % ORIGIN_DIR)

def create_route():
    if not os.path.isfile('%s/route.configured' % ORIGIN_DIR):
        logger.info("Configuring HAProxy router")
        if system('oadm policy add-scc-to-user privileged system:serviceaccount:default:router')[2]:
            log_error("Failed to service account for router")
        if system('oadm router --service-account=router --expose-metrics=true')[2]:
            log_error("Failed to expose router")
        registry_name = 'hub.openshift.%s' % OPENSHIFT_SUBDOMAIN
        if system('oc expose service docker-registry --hostname %s' % registry_name)[2]:
            log_error("Failed to expose docker registry route")
        system('touch %s/route.configured' % ORIGIN_DIR)


def secure_docker_registry():
    if not os.path.isfile('%s/secure_registry.configured' % ORIGIN_DIR):
        logger.info("Securing docker registry")
        registry_route = subprocess.check_output(("oc get route docker-registry"
            " -o template --template='{{ .spec.host }}'"), shell=True)
        registry_service_ip = subprocess.check_output(("oc get svc/docker-registry -o template"
            " --template='{{ .spec.clusterIP }}'"), shell=True)
        registry_service_port = subprocess.check_output(("oc get svc/docker-registry -o template"
            " --template='{{ (index .spec.ports 0).port }}'"), shell=True)

        # Certificate for registry service
        cmd = ("oadm ca create-server-cert --signer-cert={0}/ca.crt"
               " --signer-key={0}/ca.key --signer-serial={0}/ca.serial.txt"
               " --hostnames=\"{1},{2}\""
               " --cert={0}/registry.crt --key={0}/registry.key").format(OPENSHIFT_DIR, registry_route,
                                                                         registry_service_ip)

        if system(cmd)[2]:
            log_error("Failed to create registry certificates")

        # Create the secret for the registry certificates
        if subprocess.call(("oc secrets new registry-secret"
            " {0}/registry.crt {0}/registry.key").format(OPENSHIFT_DIR), shell=True):
            log_error("Failed to create secret for the registry certificates")

        # Add the secret volume to the registry deployment configuration
        if subprocess.call(("oc volume dc/docker-registry --add --type=secret"
            " --secret-name=registry-secret -m /etc/secrets"), shell=True):
            log_error("Failed to add the secret volume to the registry deployment configuration")

        # Enable TLS by adding the following environment variables to the registry deployment configuration
        if subprocess.call(("oc env dc/docker-registry"
                         " REGISTRY_HTTP_TLS_CERTIFICATE=/etc/secrets/registry.crt"
                         " REGISTRY_HTTP_TLS_KEY=/etc/secrets/registry.key"), shell=True):
            log_error("Failed to enable TLS")

        # Update the scheme used for the registry’s liveness probe from HTTP to HTTPS
        if subprocess.call(("oc get dc/docker-registry -o yaml"
                         " | sed -e 's/scheme: HTTP/scheme: HTTPS/g'"
                         " | oc replace -f -"), shell=True):
            log_error("Failed to update the scheme used for the registry’")

        # Copy the CA certificate to the Docker certificates directory
        subprocess.call("mkdir -p /etc/docker/certs.d/%s:%s" % \
                (registry_service_ip, registry_service_port), shell=True)
        subprocess.call("cp %s/ca.crt /etc/docker/certs.d/%s:%s" % \
                (OPENSHIFT_DIR, registry_service_ip, registry_service_port), shell=True)

        # Create cert directory
        subprocess.call("mkdir -p /etc/docker/certs.d/%s" % registry_route, shell=True)
        subprocess.call("cp %s/ca.crt /etc/docker/certs.d/%s" % \
                (OPENSHIFT_DIR, registry_route), shell=True)

        # Add "tls termination: passthrough" to already existing docker registry route
        registry_content = subprocess.check_output('oc get route docker-registry -o json', shell=True)
        registry_content = json.loads(registry_content.replace('\r\n', ''))
        registry_content['spec']['tls'] = {"termination": "passthrough"}
        registry_content = json.dumps(registry_content)
        file_discriptor, temp_file = tempfile.mkstemp(text=True)
        with open(temp_file, 'w') as fh:
            fh.write(registry_content)
        if subprocess.call('oc replace -f %s' % temp_file ,shell=True):
            log_error("Failed to add tls termination")
        os.unlink(temp_file)
        system('touch %s/secure_registry.configured' % ORIGIN_DIR)

def file_list(dir_path):
    file_list = []
    for (dirpath, dirname, filenames) in os.walk(dir_path):
        for filename in filenames:
            file_list.append('%s/%s' % (dirpath, filename))
    return file_list

def create_sample_templates():
    if not os.path.isfile('%s/templates.configured' % ORIGIN_DIR):
        logger.info("Creating example templates")
        template_list = file_list('/opt/adb/openshift/templates/common')
        template_list_adb = file_list('/opt/adb/openshift/templates/adb')
        template_list_cdk = file_list('/opt/adb/openshift/templates/cdk')

        with open('/etc/os-release') as fh:
            file_content = fh.read()

        if 'cdk' in file_content:
            template_list.extend(template_list_cdk)
        if 'adb' in file_content:
            template_list.extend(template_list_adb)
        else:
            logger.warn("Unknown variant ID")

        for template in template_list:
            logger.info("Import template %s" % template)
            if subprocess.call('oc create -f %s -n openshift' % template, shell=True):
                log_error("Failed to create templates")
        system('touch %s/templates.configured' % ORIGIN_DIR)


def user_configure():
    if not os.path.isfile('%s/user.configured' % ORIGIN_DIR):
        logger.info("Adding required roles to openshift-dev and admin user")
        subprocess.call(("oadm policy add-role-to-user basic-user"
                         " openshift-dev --config=%s/admin.kubeconfig") % OPENSHIFT_DIR, shell=True)
        subprocess.call(("oadm policy add-cluster-role-to-user cluster-admin"
                         " admin --config=%s/admin.kubeconfig") % OPENSHIFT_DIR, shell=True)
        subprocess.call(('su vagrant -l -c "oc login https://127.0.0.1:8443 -u openshift-dev -p devel'
                        ' --certificate-authority=%s/ca.crt"') % OPENSHIFT_DIR, shell=True)
        subprocess.call(('su vagrant -l -c "oc new-project sample-project'
                         ' --display-name="OpenShift sample project"'
                         ' --description="This is a sample project to demonstrate OpenShift v3""'), shell=True)
        system('touch %s/user.configured' % ORIGIN_DIR)

def main():
    wait_for_openshift_api()
    copy_openshift_client_binaries()
    create_docker_registry()
    create_route()
    secure_docker_registry()
    create_sample_templates()
    user_configure()

if __name__ == "__main__":
    main()
