#!/usr/bin/env python

# This script uses the AWS boto api to delete the selected snapshots
# in the respective aws account. The script should be run every day
# (in each respective aws account) using Rundeck or crontab. For
# Critical tagged snapshot It will keep 3 days of hourly snapshots,
# 27 daily snapshots, and 1 monthly snapshot for 6 months. This behavior
# can be over-ridden using command-line arguments.
#
# Run the program with the dryrun flag to tell the program to run, without
# make any material changes. Instead, any command that would have made
# a material change will be printed to stdout, showing what would have run.
#
#
# General algorithmic flow:
#
# Get command line arguments
# Establish connection to AWS region/account using STS assume role
# Get a list of all snapshots
#   Split in 4 lists: Critical, Dev, Stage-QA and Default
#   Filter each list removing the snapshots that won't be deleted
#   Execute the deletion of the selected snapshots

# Example command-line execution:
#
# ./trimSnapshots.py ACCOUNT_ID CROSS_ACCT_ROLE PRODUCT default_retention dev_retention stageQARetention criticalRetention Critical_hourly_ret critical_daily_ret runmode
# ./trimSnapshots.py ACCOUNT_ID CROSS_ACCT_ROLE DEFAULT 30 30 30 180 3 27 dryrun
#

import sys, getopt, os
import time, datetime
from dateutil import parser
import boto3, boto3.ec2
import re

#boto version
print boto3.__version__
print '^boto 3 version'

#command line arguments
account_id = sys.argv[1]
cross_account_role = sys.argv[2]
product_tag = sys.argv[3]
default_days_retention = sys.argv[4]
dev_days_retention = sys.argv[5]
stageqa_days_retention = sys.argv[6]
critical_days_retention = sys.argv[7]
critical_daily_days_retention = sys.argv[8]
critical_monthly_days_retention = sys.argv[9]
runmode = sys.argv[10]
# Region
region = "us-east-1"
if sys.argv[11:]:
	region = sys.argv[11]

#Get the "x days old" date.
time_limit_default=datetime.datetime.now() - datetime.timedelta(days=int(default_days_retention))
time_limit_dev=datetime.datetime.now() - datetime.timedelta(days=int(dev_days_retention))
time_limit_stageqa=datetime.datetime.now() - datetime.timedelta(days=int(stageqa_days_retention))
time_limit_critical=datetime.datetime.now() - datetime.timedelta(days=int(critical_days_retention))
time_limit_daily_critical=datetime.datetime.now() - datetime.timedelta(days=int(critical_daily_days_retention))
time_limit_monthly_critical=datetime.datetime.now() - datetime.timedelta(days=int(critical_monthly_days_retention))

# Initialize the STS Client.
sts_client = boto3.client('sts', region_name = region)

# Call the assume_role method of the STSConnection object and pass the role
# ARN and a role session name.

assumedRoleObject = sts_client.assume_role(
    RoleArn="arn:aws:iam::" + str(account_id) + ":role/" + str(cross_account_role),
    RoleSessionName="EBS-Snapshots-Pruning",
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


snapshots = []
snapshots_paginator = []

#get the entire list of snapshots and amis owned by the account
snapshots_paginator = ec2.describe_snapshots(OwnerIds=[str(account_id)],MaxResults=1000)
if len(snapshots_paginator['Snapshots']) > 0:
	snapshots.extend(snapshots_paginator['Snapshots'])

while 'NextToken' in snapshots_paginator:
	snapshots_paginator = ec2.describe_snapshots(OwnerIds=[str(account_id)],MaxResults=1000,NextToken=snapshots_paginator['NextToken'])
	if len(snapshots_paginator['Snapshots']) > 0:
		snapshots.extend(snapshots_paginator['Snapshots'])


ami_list = ec2.describe_images(Owners=[str(account_id)])
snapshot_belong_to_ami = list()
for im in ami_list['Images']:
	for volume in im['BlockDeviceMappings']:
		if 'Ebs' in volume:
			if 'SnapshotId' in volume['Ebs']:
				if str(volume['Ebs']['SnapshotId']) not in snapshot_belong_to_ami and str(volume['Ebs']['SnapshotId']) != "None":
					snapshot_belong_to_ami.append(str(volume['Ebs']['SnapshotId']))


#
#functions to obtain the list of snapshots by tag.
#

#get snapshots list
def getSnapshotList(policy):

	snaps = []
	snaptmp = set()
	keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.

	for snapshot in snapshots:
		snaptmp = set(snapshot)
		if keytags in snaptmp:
			if re.search(str(product_tag),str(snapshot[keytags])) and re.search(str(policy),str(snapshot[keytags])):
				if str(snapshot['SnapshotId']) not in snapshot_belong_to_ami:
					if not re.search('preserve_snapshot',str(snapshot[keytags])):
						snaps.append(snapshot)


	return snaps


#obtain and returns a list of snapshots with "Critical" value for "Snapshot" key-tag
def getCriticalList():

	return getSnapshotList('Critical')


#obtain and returns a list of snapshots with "Dev" value for "Snapshot" key-tag
def getDevList():

	return getSnapshotList('Dev')


#obtain and returns a list of snapshots with "Stage-QA" value for "Snapshot" key-tag
def getStageQAList():

	return getSnapshotList('Stage-QA')


#obtain and returns a list of snapshots with "Default" value for "Snapshot" key-tag associated with a product.
def getDefaultList():

	return getSnapshotList('Default')


#obtain and returns a list of snapshots with no tags atatched
def getDefaultListNoPolicyTags():

	snapsDefault = []
	snaptmp = set()
	keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.

	for snapshot in snapshots:
		snaptmp = set(snapshot)
		if keytags in snaptmp:
			if not re.search('Product',str(snapshot[keytags])) and not re.search('Snapshot',str(snapshot[keytags])):
				if str(snapshot['SnapshotId']) not in snapshot_belong_to_ami and str(snapshot['SnapshotId']) not in snapsDefault:
					if not re.search('preserve_snapshot',str(snapshot[keytags])):
						snapsDefault.append(snapshot)

		else:
			if str(snapshot['SnapshotId']) not in snapshot_belong_to_ami and str(snapshot['SnapshotId']) not in snapsDefault:
				snapsDefault.append(snapshot)

	return snapsDefault


#selects and create a list of Critical snapshots for deletion.
def criticalToDelete(snapsCriticalList):

	listCriticalToDelete = []
	listControlDuplicates = []

	for criticalSnap in snapsCriticalList:

		# Adds snapshot to pruning list if creation date is older than 180 days ago (default value).
		if criticalSnap['StartTime'].date() < time_limit_critical.date():
			if criticalSnap['SnapshotId'] not in listControlDuplicates:
				listCriticalToDelete.append(criticalSnap)
				listControlDuplicates.append(criticalSnap['SnapshotId'])

		# Adds snapshot to pruning list if creation date is older than 27 days ago (default value).
		# Also, preserves the snapshot created on 18th day (reference day).
		if criticalSnap['StartTime'].date() < time_limit_monthly_critical.date():
			if criticalSnap['StartTime'].date().day != 18:
				if criticalSnap['SnapshotId'] not in listControlDuplicates:
					listCriticalToDelete.append(criticalSnap)
					listControlDuplicates.append(criticalSnap['SnapshotId'])

		# Adds snapshot to pruning list if creation date is older than 2 days ago (default value).
		# Also, preserves the snapshot created on 3AM (UTC).
		if criticalSnap['StartTime'].date() < time_limit_daily_critical.date():
			if criticalSnap['StartTime'].time().hour != 3:
				if criticalSnap['SnapshotId'] not in listControlDuplicates:
					listCriticalToDelete.append(criticalSnap)
					listControlDuplicates.append(criticalSnap['SnapshotId'])

	return listCriticalToDelete


#selects and create a list of Dev snapshots to delete
def devToDelete(snapsDevList):

	listDevToDelete = []
	for devSnap in snapsDevList:
		if devSnap['StartTime'].date() < time_limit_dev.date():
			listDevToDelete.append(devSnap)

	return listDevToDelete


#selects and create a list of Stage-QA snapshots to delete
def stageQAToDelete(snapsStageQAList):

	listStageQAToDelete = []
	for stageQASnap in snapsStageQAList:
		if stageQASnap['StartTime'].date() < time_limit_stageqa.date():
			listStageQAToDelete.append(stageQASnap)

	return listStageQAToDelete


#selects and create a list of default snapshots to delete
def defaultToDelete(snapsDefaultList):

	listDefaultToDelete = []
	for defaultSnap in snapsDefaultList:
		if defaultSnap['StartTime'].date() < time_limit_default.date():
			listDefaultToDelete.append(defaultSnap)

	return listDefaultToDelete


#deletes snapshots of the given lists
def deleteSnapshots(ec2, criticals, devs , stageQAs, defaults):

	print "------------ Quantity of snapshots to delete per policy tag ------------"
	print ""
	print "Critical: " + str(len(criticals))
	print "Dev: " + str(len(devs))
	print "Stage-QA: " + str(len(stageQAs))
	print "Default: " + str(len(defaults))
	print ""

	print "------------ Snapshots to delete ------------"
	print ""
	print "Syntax:  snapshot id | policy type | volume id | volume size | description"

	if len(criticals) > 0:
		print ""
		print "Critical tag: "
		for crit in criticals:
			print str(crit['SnapshotId']) + "|" + "Critical" + "|" + str(crit['VolumeId']) + "|" +  str(crit['VolumeSize']) + "GB|" +  str(crit['Description'])
			try:
				if runmode != "dryrun":
					ec2.delete_snapshot(SnapshotId=crit['SnapshotId'])
			except:
				print "Error: Can't delete snapshot: " + str(crit['SnapshotId'])

	if len(devs) > 0:
		print ""
		print "Dev tag: "
		for dev in devs:
			print str(dev['SnapshotId']) + "|" + "Dev" + "|" + str(dev['VolumeId']) + "|" +  str(dev['VolumeSize']) + "GB|" +  str(dev['Description'])
			try:
				if runmode != "dryrun":
					ec2.delete_snapshot(SnapshotId=dev['SnapshotId'])
			except:
				print "Error: Can't delete snapshot: " + str(dev['SnapshotId'])

	if len(stageQAs) > 0:
		print ""
		print "Stage-QA tag: "
		for stage in stageQAs:
			print str(stage['SnapshotId']) + "|" + "Stage-QA" + "|" + str(stage['VolumeId']) + "|" +  str(stage['VolumeSize']) + "GB|" +  str(stage['Description'])
			try:
				if runmode != "dryrun":
					ec2.delete_snapshot(SnapshotId=stage['SnapshotId'])
			except:
				print "Error: Can't delete snapshot: " + str(stage['SnapshotId'])

	if len(defaults) > 0:
		print ""
		print "Default tag: "
		for defa in defaults:
			print str(defa['SnapshotId']) + "|" + "Default" + "|" + str(defa['VolumeId']) + "|" +  str(defa['VolumeSize']) + "GB|" +  str(defa['Description'])
			try:
				if runmode != "dryrun":
					ec2.delete_snapshot(SnapshotId=defa['SnapshotId'])
			except:
				print "Error: Can't delete snapshot: " + str(defa['SnapshotId'])


#deletes snapshots of the given lists
def deleteSnapshotsNoPolicyAttached(ec2, defaults):

	print "------------ Quantity of snapshots to delete - No Snapshot Policy Attached ------------"
	print ""
	print "Defaults to delete: " + str(len(defaults))
	print ""
	print "Syntax:  snapshot id | policy type | volume id | volume size | description"
	print ""

	print "------------ Snapshots to delete ------------"
	for deftodelete in defaults:
		print str(deftodelete['SnapshotId']) + "|" + "Default" + "|" + str(deftodelete['VolumeId']) + "|" +  str(deftodelete['VolumeSize']) + "GB|" + str(deftodelete['Description'])
		try:
			if runmode != "dryrun":
				ec2.delete_snapshot(SnapshotId=deftodelete['SnapshotId'])
		except:
			print "Error: Can't delete snapshot: " + str(deftodelete['SnapshotId'])
			e = sys.exc_info()[0]
			print("Exception:   %s" %e)


#
# main()
#

#Execution
deleteSnapshots(ec2,criticalToDelete(getCriticalList()),devToDelete(getDevList()),stageQAToDelete(getStageQAList()),defaultToDelete(getDefaultList()))
deleteSnapshotsNoPolicyAttached(ec2,defaultToDelete(getDefaultListNoPolicyTags()))
