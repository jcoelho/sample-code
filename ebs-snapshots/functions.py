#
# Function definitions.
#
import re
import sys, getopt, os, time
from dateutil import parser

product_tag = sys.argv[3]
runmode = sys.argv[4]
dev_reference_days = sys.argv[5]
qa_reference_days = sys.argv[6]
default_reference_days = sys.argv[7]
dev_snapshots_date = 0
qa_snapshots_date = 0
default_snapshots_date = 0

#function to obtain the list of volumes that belong to ASG of a specific product
def volumesAsg(ec2, all_groups, tag_product, tag_policy, volumes_per_instances_in_asg):

    vols_final = []
    volumes = list()
    asg_by_product = []
    asg_by_product_no_authnpub = []
    keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.

    for gr in all_groups:
        if keytags in gr:
            for i in range(0,len(gr[keytags])): #Check ASG tags in key=value format
                if str(gr[keytags][i]['Value']) == tag_product and str(gr[keytags][i]['Key']) == 'Product':
                    asg_by_product.append(gr)

    # Filters author and publisher auto scaling groups.
    for ap in asg_by_product:
        if not authorPublisherInASGroup(ap):
            asg_by_product_no_authnpub.append(ap)

    for g in asg_by_product_no_authnpub:
        if keytags in g:
            for k in range(0,len(g[keytags])): #Check ASG tags in key=value format
                if str(g[keytags][k]['Value']) == tag_policy and str(g[keytags][k]['Key']) == 'Snapshot':
                    for instance in g['Instances']:
                        try:
                            vols = ec2.describe_volumes(Filters=[{'Name':'attachment.instance-id', 'Values':[str(instance['InstanceId'])]}])
                            for v in vols['Volumes']:
                                if v['VolumeId'] not in vols_final:
                                    vols_final.append(v['VolumeId'])
                                    volumes_per_instances_in_asg[v['VolumeId']] = {'Instance': str(instance['InstanceId']), 'ASG': str(g['AutoScalingGroupName'])}

                        except:
                            e = sys.exc_info()[0]
                            print("Exception:   %s" %e)

    return vols_final


#function to obtain the list of volumes that belong to ASG, no product and no snapshot tag attached
def volumesAsgDefault(ec2, all_groups, volumes_per_instances_in_asg):

    vols_final = []
    volumes = list()
    asg_no_prodnsnap = []
    asg_by_product_no_authnpub = []
    keyinstances = 'Instances'    # To avoid KeyError exception caused by instances not associated to the related object.

    for gr in all_groups:
        if not asgAttachedTag(gr,'Product') and not asgAttachedTag(gr,'Snapshot'):
            asg_no_prodnsnap.append(gr)

    # Filters author and publisher auto scaling groups.
    for ap in asg_no_prodnsnap:
        if not authorPublisherInASGroup(ap):
            asg_by_product_no_authnpub.append(ap)

    for g in asg_by_product_no_authnpub:
        if keyinstances in g:
            for instance in g[keyinstances]:
                try:
                    vols = ec2.describe_volumes(Filters=[{'Name':'attachment.instance-id', 'Values':[str(instance['InstanceId'])]}])
                    for v in vols['Volumes']:
                        if v['VolumeId'] not in vols_final:
                            vols_final.append(v['VolumeId'])
                            volumes_per_instances_in_asg[v['VolumeId']] = {'Instance': str(instance['InstanceId']), 'ASG': str(g['AutoScalingGroupName'])}

                except:
                    e = sys.exc_info()[0]
                    print("Exception:   %s" %e)

    return vols_final


#function to evaluate if an auto scaling group has attached the snapshot or product tag.
def asgAttachedTag(asgroup, tag):

    policy_tag_found = False
    keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.

    if keytags in asgroup:
        for i in range(0,len(asgroup[keytags])):
            if str(asgroup[keytags][i]['Key']) == str(tag) and str(asgroup[keytags][i]['Value']) != '':
                policy_tag_found = True

    return policy_tag_found


def authorPublisherInASGroup(ap):

    asgroup_tag_found = False
    keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.

    # Checks for Author or Publisher Scale Group Cloudformation Tag.
    if keytags in ap:
        for j in range(0,len(ap[keytags])):
            if str(ap[keytags][j]['Key']) == 'aws:cloudformation:logical-id' and (str(ap[keytags][j]['Value']) == 'AuthorScaleGroup' or str(ap[keytags][j]['Value']) == 'PublishScaleGroup'):
                asgroup_tag_found = True

    return asgroup_tag_found


#function to obtain the list of volumes that belong to an instance
def volumesInstancesIndividual(ec2, tag_product, tag_policy, volumes_per_instances_noassoc_asg):

    vol_instances = []
    instances_paginator = []
    reservations = []

    instances_paginator = ec2.describe_instances(Filters=[{'Name': 'tag:Product', 'Values':[tag_product]}, {'Name': 'tag:Snapshot', 'Values':[tag_policy]}])
    if len(instances_paginator['Reservations']) > 0:
        reservations.extend(instances_paginator['Reservations'])

    while 'NextToken' in instances_paginator:
        instances_paginator = ec2.describe_instances(Filters=[{'Name': 'tag:Product', 'Values':[tag_product]}, {'Name': 'tag:Snapshot', 'Values':[tag_policy]}], NextToken=instances_paginator['NextToken'])
        if len(instances_paginator['Reservations']) > 0:
            reservations.extend(instances_paginator['Reservations'])

    instances = [i for r in reservations for i in r['Instances']]

    for instancia in instances:
        if not instanceAttachedASGroupTag(instancia) and instanceAttachedTag(instancia, "Product", tag_product, True) and instanceAttachedTag(instancia, "Snapshot", tag_policy, True) and not instanceAttachedTag(instancia, "aws:cloudformation:logical-id", "AuthorScaleGroup", True) and not instanceAttachedTag(instancia, "aws:cloudformation:logical-id", "PublishScaleGroup", True):
            try:
                volumes = ec2.describe_volumes(Filters=[{'Name':'attachment.instance-id', 'Values':[str(instancia['InstanceId'])]}])
                for v in volumes['Volumes']:
                    if v['VolumeId'] not in vol_instances:
                        vol_instances.append(v['VolumeId'])
                        volumes_per_instances_noassoc_asg[v['VolumeId']] = {'Instance': str(instancia['InstanceId']), 'ASG': 'N/A'}

            except:
                e = sys.exc_info()[0]
                print("Exception:   %s" %e)

    return vol_instances


#function to obtain the list of volumes that belong to instances not associated to auto scaling groups.
def volumesInstancesIndividualDefault(ec2, volumes_per_instances_noassoc_asg):

    vol_instances = []
    reservations_paginator = []
    reservations = []

    reservations_paginator = ec2.describe_instances()
    if len(reservations_paginator['Reservations']) > 0:
        reservations.extend(reservations_paginator['Reservations'])

    while 'NextToken' in reservations_paginator:
        reservations_paginator = ec2.describe_instances(NextToken=reservations_paginator['NextToken'])
        if len(reservations_paginator['Reservations']) > 0:
            reservations.extend(reservations_paginator['Reservations'])

    instances = [i for reserv in reservations for i in reserv['Instances']]
    for instancia in instances:
        if not instanceAttachedASGroupTag(instancia) and not instanceAttachedTag(instancia, 'Product', '', False) and not instanceAttachedTag(instancia, 'Snapshot', '', False) and not instanceAttachedTag(instancia, "aws:cloudformation:logical-id", "AuthorScaleGroup", True) and not instanceAttachedTag(instancia, "aws:cloudformation:logical-id", "PublishScaleGroup", True):
            try:
                volumes = ec2.describe_volumes(Filters=[{'Name':'attachment.instance-id', 'Values':[str(instancia['InstanceId'])]}])
                for v in volumes['Volumes']:
                    if v['VolumeId'] not in vol_instances:
                        vol_instances.append(v['VolumeId'])
                        volumes_per_instances_noassoc_asg[v['VolumeId']] = {'Instance': str(instancia['InstanceId']), 'ASG': 'N/A'}

            except:
                e = sys.exc_info()[0]
                print("Exception:   %s" %e)

    return vol_instances


#checks if instance id belongs to an AS Group.
def instanceAttachedASGroupTag(instance):

    return instanceAttachedTag(instance, 'aws:autoscaling:groupName', '', False)


#function to evaluate if an instance has attached a given tag (key and value or key only).
def instanceAttachedTag(instance, tagkey, tagvalue, checkvalue):

    tag_found = False
    keytags = 'Tags'    # To avoid KeyError exception caused by tags not attached to the related object.
    regex_instance2 = True  # Initial auxiliar value.

    if keytags in instance:
        regex_instance1 = re.search(tagkey,str(instance[keytags]))

        if checkvalue:
            regex_instance2 = re.search(tagvalue,str(instance[keytags]))

        if regex_instance1 and regex_instance2:
            tag_found = True

    return tag_found


#checks if reservation object id exists in given list of objects
def existsReservation(id,reservations):

    flag = False

    for res in reservations:
        if str(res['ReservationId']) == str(id):
            flag = True

    return flag


#returns true if finds a snapshot created after #dateTag
def getSnapshotVolume(ec2, volumeId, dateTag):

    volList = []
    flag = False
    snaps = ec2.describe_snapshots(Filters=[{'Name': 'volume-id', 'Values':[volumeId]}])

    for i in range(0,len(snaps['Snapshots'])):
        if snaps['Snapshots'][i]['StartTime'].date() > dateTag.date():
            flag = True

    return flag


#finds if exists the volumme id in the given lists
def getVolumeASGInstanceInfo(volume_id, volume_list_a, volume_list_b):

    for volumen, metadata in volume_list_a.items():
        if volumen == volume_id:
            return metadata

    for volumen, metadata in volume_list_b.items():
        if volumen == volume_id:
            return metadata

    return [{'Instance': 'N/A', 'ASG': 'N/A'}]


# creates the snapshots applying the correct policies from list of volumes.
def createSnapshots(ec2, list_volumes_critical, list_volumes_dev, list_volumes_qa, list_volumes_default, list_volumes_default_cp,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg):

    volume_metadata = []

    if len(list_volumes_critical) > 0:
        for volum in list_volumes_critical:

            try:
                snapshot_critical = ec2.create_snapshot(VolumeId=str(volum), Description=str("Critical-Policy" + "--" + "From Vol: " + volum))
                time.sleep(2)
                response = ec2.create_tags(Resources=[str(snapshot_critical['SnapshotId'])], Tags=[{'Key': 'Product', 'Value': str(product_tag)}, {'Key': 'Snapshot', 'Value': 'Critical'}])
                volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                print str(volum) + "|" + str(snapshot_critical['SnapshotId']) + "|" + "Critical" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

            except:
                e = sys.exc_info()[0]
                print("Exception:   %s" %e)

    if len(list_volumes_dev) > 0:
        for volum in list_volumes_dev:

            if getSnapshotVolume(ec2, volum, dev_snapshots_date):
                print "Snapshot newest than " + str(dev_reference_days) + " days found (Dev Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                try:
                    snapshot_dev = ec2.create_snapshot(VolumeId=str(volum), Description=str("Dev-Policy" + "--" + "From Vol: " + volum))
                    time.sleep(2)
                    response = ec2.create_tags(Resources=[str(snapshot_dev['SnapshotId'])], Tags=[{'Key': 'Product', 'Value': str(product_tag)}, {'Key': 'Snapshot', 'Value': 'Dev'}])
                    volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                    print str(volum) + "|" + str(snapshot_dev['SnapshotId']) + "|" + "Dev" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

                except:
                    e = sys.exc_info()[0]
                    print("Exception:   %s" %e)

    if len(list_volumes_qa) > 0:
        for volum in list_volumes_qa:

            if getSnapshotVolume(ec2, volum, qa_snapshots_date):
                print "Snapshot newest than " + str(qa_reference_days) + " days found (Stage-QA Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                try:
                    snapshot_qa = ec2.create_snapshot(VolumeId=str(volum), Description=str("StageQA-Policy" + "--" + "From Vol: " + volum))
                    time.sleep(2)
                    response = ec2.create_tags(Resources=[str(snapshot_qa['SnapshotId'])], Tags=[{'Key': 'Product', 'Value': str(product_tag)}, {'Key': 'Snapshot', 'Value': 'Stage-QA'}])
                    volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                    print str(volum) + "|" + str(snapshot_qa['SnapshotId']) + "|" + "Stage-QA" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

                except:
                    e = sys.exc_info()[0]
                    print("Exception:   %s" %e)

    if len(list_volumes_default) > 0:
        for volum in list_volumes_default:

            if getSnapshotVolume(ec2, volum, default_snapshots_date):
                print "Snapshot newest than " + str(default_reference_days) + " day(s) found (Default Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                try:
                    snapshot_default = ec2.create_snapshot(VolumeId=str(volum), Description=str("Default-Policy" + "--" + "From Vol: " + volum))

                    if str(product_tag) != "DEFAULT":
                        time.sleep(2)
                        response = ec2.create_tags(Resources=[str(snapshot_default['SnapshotId'])], Tags=[{'Key': 'Product', 'Value': str(product_tag)}, {'Key': 'Snapshot', 'Value': 'Default'}])
                        volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                        print str(volum) + "|" + str(snapshot_default['SnapshotId']) + "|" + "Default" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

                except:
                    e = sys.exc_info()[0]
                    print("Exception:   %s" %e)

    if len(list_volumes_default_cp) > 0:
        for volum in list_volumes_default_cp:

            try:
                snapshot_defcritical = ec2.create_snapshot(VolumeId=str(volum), Description=str("Default-Critical-Policy" + "--" + "From Vol: " + volum))
                time.sleep(2)
                response = ec2.create_tags(Resources=[str(snapshot_defcritical['SnapshotId'])], Tags=[{'Key': 'Product', 'Value': str(product_tag)}, {'Key': 'Snapshot', 'Value': 'Critical'}])
                volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                print str(volum) + "|" + str(snapshot_defcritical['SnapshotId']) + "|" + "Default Critical" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

            except:
                e = sys.exc_info()[0]
                print("Exception:   %s" %e)


# simulates the creation of the snapshots applying the correct policies from list of volumes.
def createSnapshotsDryRun(ec2, list_volumes_critical, list_volumes_dev, list_volumes_qa, list_volumes_default, list_volumes_default_cp,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg):

    volume_metadata = []

    if  len(list_volumes_critical) > 0:
        for volum in list_volumes_critical:
            volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
            print str(volum) + "|" + "Critical" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

    if len(list_volumes_dev) > 0:
        for volum in list_volumes_dev:
            if getSnapshotVolume(ec2, volum, dev_snapshots_date):
                print "Snapshot newest than " + str(dev_reference_days) + " days found (Dev Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                print str(volum) + "|" + "Dev" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

    if len(list_volumes_qa) > 0:
        for volum in list_volumes_qa:
            if getSnapshotVolume(ec2, volum, qa_snapshots_date):
                print "Snapshot newest than " + str(qa_reference_days) + " days found (Stage-QA Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                print str(volum) + "|" + "Stage-QA" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

    if len(list_volumes_default) > 0:
        for volum in list_volumes_default:
            if getSnapshotVolume(ec2, volum, default_snapshots_date):
                print "Snapshot newest than " + str(default_reference_days) + " day(s) found (Default Policy). Avoiding the creation of snapshot for: " + str(volum)
            else:
                volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
                print str(volum) + "|" + "Default" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

    if len(list_volumes_default_cp) > 0:
        for volum in list_volumes_default_cp:
            volume_metadata = getVolumeASGInstanceInfo(volum,volumes_per_instances_in_asg,volumes_per_instances_noassoc_asg)
            print str(volum) + "|" + "Default Critical" + "|" + str(volume_metadata['Instance']) + "|" + str(volume_metadata['ASG'])

#
# End of function definitions.
#
