#!/usr/bin/env python

# This script uses the AWS boto api to create snapshots in the
# respective aws account according to a predefined set of policies.
# The frequency the script should be running is defined previously
# and is defined depending of the aws account and product.
# The script should be configured to run using Rundeck or crontab.
#
# Run the program with the dryrun flag to tell the program to run, whithout
# make any changes to the environment. Instead, any command that would have made
# a material change will be printed to stdout, showing what would have run.
#
#
# General algorithmic flow:
#
# Get command line arguments
# Establish connection to AWS region/account using STS assume role operation
# Set the relative timestamps according to policies
# Get a list of volumes for the Critical, Dev, Stage-QA and Default policies
# Execute the creation of snapshots given the listed volumes

# Example command-line execution:
#
# ./snapCreation.py ACCOUNT_ID CROSS_ACCT_ROLE PRODUCT_TAG dryrun 7 3 2
# ./snapCreation.py ACCOUNT_ID CROSS_ACCT_ROLE PRODUCT_TAG exec 7 3 2
#

import sys, getopt, os
import time, datetime
import boto3, boto3.ec2
import tenacity
import functions
import constants as c
from guppy import hpy

#
# To test the script execution time and memory usage.
#
start_time = time.time()
h = hpy()

#boto3 version
print boto3.__version__
print '^boto3 version'

#command line arguments
account_id = sys.argv[1]
cross_account_role = sys.argv[2]
product_tag = sys.argv[3]
runmode = sys.argv[4]
dev_reference_days = sys.argv[5]
qa_reference_days = sys.argv[6]
default_reference_days = sys.argv[7]

# Region
region = "us-east-1"
if sys.argv[8:]:
    region = sys.argv[8]

sts_client = boto3.client('sts', region_name = region)

# Call the assume_role method of the STSConnection object and pass the role
# ARN and a role session name.

assumedRoleObject = sts_client.assume_role(
    RoleArn="arn:aws:iam::" + str(account_id) + ":role/" + str(cross_account_role),
    RoleSessionName="EBS-Snapshots-Creation",
	DurationSeconds=3600
)

# From the response that contains the assumed role, get the temporary
# credentials that can be used to make subsequent API calls
credentials = assumedRoleObject['Credentials']

#Connection to AWS
try:
    ec2 = boto3.client('ec2',
    aws_access_key_id = credentials['AccessKeyId'],
    aws_secret_access_key = credentials['SecretAccessKey'],
    aws_session_token = credentials['SessionToken'],
    region_name = region
    )

except:
    print "ec2 connection not working"
    exit(1)

try:
    autoscale = boto3.client('autoscaling',
    aws_access_key_id = credentials['AccessKeyId'],
    aws_secret_access_key = credentials['SecretAccessKey'],
    aws_session_token = credentials['SessionToken'],
    region_name = region
    )

except:
    print "autoscaling connection not working"
    exit(1)

#
# main()
#

# Get the "x" days old date by policy.
functions.dev_snapshots_date =  datetime.datetime.now() - datetime.timedelta(days=int(dev_reference_days))
functions.qa_snapshots_date =  datetime.datetime.now() - datetime.timedelta(days=int(qa_reference_days))
functions.default_snapshots_date =  datetime.datetime.now() - datetime.timedelta(days=int(default_reference_days))

#Lists
critical_volume_list = []
dev_volume_list = []
qa_volume_list = []
default_volume_list = []
no_backup_volume_list = []
default_critical_volume_list = []
all_groups=[]
volumes_per_instances_in_asg = {}
volumes_per_instances_noassoc_asg = {}

# Error retrying to get all auto scaling groups.
@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=c.MAX_RETRIES))
def get_all_as_groups(autoscale):

    groups_paginator = []
    all_groups = []

    groups_paginator = autoscale.describe_auto_scaling_groups()
    if len(groups_paginator['AutoScalingGroups']) > 0:
        all_groups.extend(groups_paginator['AutoScalingGroups'])

    while 'NextToken' in groups_paginator:
        groups_paginator = autoscale.describe_auto_scaling_groups(NextToken=groups_paginator['NextToken'])
        if len(groups_paginator['AutoScalingGroups']) > 0:
            all_groups.extend(groups_paginator['AutoScalingGroups'])

    return all_groups

# get all autoscaling groups
all_groups = get_all_as_groups(autoscale)

if product_tag == "DEFAULT":

    default_critical_volume_list = list(set(functions.volumesAsgDefault(ec2,all_groups,volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividualDefault(ec2,volumes_per_instances_noassoc_asg)))

    # verbose: Print some information to see after execution.
    print ""
    print "Default: " + str(len(default_critical_volume_list))
    print "------ Current Date ------"
    print  datetime.datetime.now()
    print ""
    print "------- Reference date ------------"
    print ""
    print "Reference date for Default: " + str(functions.default_snapshots_date)
    print ""

else:

    critical_volume_list = list(set(functions.volumesAsg(ec2,all_groups,product_tag,"Critical",volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividual(ec2,product_tag,"Critical",volumes_per_instances_noassoc_asg)))
    dev_volume_list = list(set(functions.volumesAsg(ec2,all_groups,product_tag,"Dev",volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividual(ec2,product_tag,"Dev",volumes_per_instances_noassoc_asg)))
    qa_volume_list = list(set(functions.volumesAsg(ec2,all_groups,product_tag,"Stage-QA",volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividual(ec2,product_tag,"Stage-QA",volumes_per_instances_noassoc_asg)))
    default_volume_list = list(set(functions.volumesAsg(ec2,all_groups,product_tag,"Default",volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividual(ec2,product_tag,"Default",volumes_per_instances_noassoc_asg)))
    no_backup_volume_list = list(set(functions.volumesAsg(ec2,all_groups,product_tag,"No_Backup",volumes_per_instances_in_asg)) | set(functions.volumesInstancesIndividual(ec2,product_tag,"No_Backup",volumes_per_instances_noassoc_asg)))

    # verbose: Print some information to see after execution.
    print "------ Volume quantity per policy tag ------- "
    print ""
    print "Critical: " + str(len(critical_volume_list))
    print "Dev: "  + str(len(dev_volume_list))
    print "Stage-QA: " + str(len(qa_volume_list))
    print "Default: " + str(len(default_volume_list))
    print "No Backup Volumes: " + str(len(no_backup_volume_list))
    print ""
    print "List of No Backup volumes:"
    print ""
    print no_backup_volume_list
    print ""
    print ""
    print "------ Current Date ------"
    print  datetime.datetime.now()
    print ""
    print ""
    print "------- Reference dates ------------"
    print ""
    print "Reference date for Dev: " + str(functions.dev_snapshots_date)
    print "Reference date for Stage-QA: " + str(functions.qa_snapshots_date)
    print "Reference date for Default: " + str(functions.default_snapshots_date)
    print ""

if runmode != "dryrun":
    print ""
    print "------- Execution -------"
    print ""
    print "Creating Snapshots . . ."
    print "Syntax:  volume-id | snapshot id | policy type | instance id | autoscaling group name"
    print ""

    #Execution
    print functions.createSnapshots(ec2,critical_volume_list,dev_volume_list,qa_volume_list,default_volume_list,default_critical_volume_list,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
    print "---------End of Execution---------"

else:
    print ""
    print "------- Dry run execution -------"
    print ""
    print "Simulation of snapshots to be created:"
    print "Syntax:  volume-id | policy type | instance id | autoscaling group name"
    print ""

    #Execution
    print functions.createSnapshotsDryRun(ec2,critical_volume_list,dev_volume_list,qa_volume_list,default_volume_list,default_critical_volume_list,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
    print "------- End of Dry run execution -------"

#
# Prints total execution time and memory usage.
#
print("Total execution time:    --- %s seconds ---" % (time.time() - start_time))
print "Profiling summary:"
print h.heap()
