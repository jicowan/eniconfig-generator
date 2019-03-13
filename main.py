import ipaddress
from boto3 import client
from boto3 import resource
from kubernetes import config

ec2cli = client('ec2')
ec2res = resource('ec2')

class Eniconfig:
    def __init__(self, name, subnetId, securityGroupId):
        self.name = name
        self.subnetId = subnetId
        self.securityGroupId = securityGroupId

def generate_subnets(vpc_cidr, subnet_mask):
    subnets = []
    subnet_cidrs = ipaddress.ip_network(vpc_cidr).subnets(new_prefix=subnet_mask)
    for subnet_cidr in subnet_cidrs:
        subnets.append(subnet_cidr.compressed)
    return subnets

def get_vpcs():
    response = []
    vpcs = ec2cli.describe_vpcs()['Vpcs']
    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        vpc_cidrs = list(map(lambda x: x['CidrBlock'], vpc['CidrBlockAssociationSet']))
        response.append({'VpcId': vpc_id, 'CidrBlocks': vpc_cidrs})
    return response

def get_azs():
    response = ec2cli.describe_availability_zones()
    zones = map(lambda x: x['ZoneName'], response['AvailabilityZones'])
    return list(zones)

def create_cidr_block(cidr_block, vpc_id):
    ec2cli.associate_vpc_cidr_block(
        CidrBlock=cidr_block,
        VpcId=vpc_id
    )

def create_subnets(az, cidr_block, vpc_id, cluster_name):
    vpc = ec2res.Vpc(vpc_id)
    response = vpc.create_subnet(
        AvailabilityZone=az,
        CidrBlock=cidr_block,
        DryRun=False
    )
    print(response.subnet_id)
    subnet = ec2res.Subnet(response.subnet_id)
    subnet.create_tags(
        Tags=[
            {
                'Key': 'kubernetes.io/cluster/' + cluster_name,
                'Value': 'shared'
            },
        ]
    )

def verify_overlap(cidr_block, vpc_id):
    vpc = ec2res.Vpc(vpc_id)
    vpc_subnets = vpc.subnets.all()
    for subnet in vpc_subnets:
        if ipaddress.ip_network(subnet.cidr_block).overlaps(ipaddress.ip_network(cidr_block)):
            return True

def create_eniconfig(Eniconfig):
    #//TODO change to method inputs to tuple or class
    with open(Eniconfig.name + ".yaml", "w") as f:
        f.write("""apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name:""" + Eniconfig.name + """
spec:
  subnet:""" + Eniconfig.subnetId + """
securityGroups:
- """ + Eniconfig.securityGroupId)
    f.close()

def get_cluster_name():
    cluster_config = config.kube_config.list_kube_config_contexts()
    cluster_name = cluster_config[1]['context']['cluster']
    if '.' in cluster_name:
        cluster_name = cluster_name.split('.')[0]
    return cluster_name

def get_security_groups(vpc_id):
    response = ec2cli.describe_security_groups(
        Filters=[
            {
                'Name': 'vpc-id',
                'Values': [vpc_id]
            }
        ]
    )['SecurityGroups']
    sgs = []
    for sg in response:
        sgs.append({'SecurityGroupId': sg['GroupId'], 'SecurityGroupName': sg['GroupName']})
    return sgs
#-------------------------------------------------------------------------------------------------

vpcs = []
vpc_ids = get_vpcs()
for vpc_id in vpc_ids:
    vpcs.append(vpc_id.get('VpcId'))

for i in range(len(vpcs)):
    print(i, vpcs[i])

vpc_index = int(input('Choose a VPC ID: '))
security_groups = get_security_groups(vpcs[vpc_index])

for i in range(len(security_groups)):
    print(i, security_groups[i]['SecurityGroupId'], security_groups[i]['SecurityGroupName'])
sg_index = int(input('Choose a security group: '))

vpc_cidr = str(input('Enter VPC CIDR range, e.g. 100.64.0.0/16: '))
subnet_mask = int(input('Enter subnet mask, e.g. 24: '))

azs = get_azs()
subnets = generate_subnets(vpc_cidr, subnet_mask)
cluster_name = get_cluster_name()
#//TODO create VPC CIDR
create_cidr_block(vpc_cidr, vpcs[vpc_index])
i = 0
for az in azs:
    while verify_overlap(subnets[i], vpcs[vpc_index]):
        i = i + 1
    create_subnets(az, subnets[i], vpcs[vpc_index], cluster_name)
    ec = Eniconfig(az, subnets[i], security_groups[sg_index]['SecurityGroupId'])
    create_eniconfig(ec)




