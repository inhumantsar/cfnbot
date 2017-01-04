import boto3
import yaml
import json
import logging
import click
import sys
from datetime import datetime
from collections import defaultdict
from subprocess import call
from .cfnbot import StackSet, Stack


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger('botocore').setLevel(logging.WARNING) # too much noise.
ch = logging.StreamHandler(stream=sys.stdout)
logger.addHandler(ch)
# sys.tracebacklimit = 0 this is ignored these days. probably because they
# want people to use exception hooks. but man. i'm lazy and stuck in my ways.

### because i'm a space cadet, the parameter list:
# StackName: string, starts with a letter, alphanum+hyphen, max 128 chars.
# Capabilities: list, CAPABILITY_IAM or CAPABILITY_NAMED_IAM
#   only req'd if AWS::IAM::AccessKey, ::InstanceProfile, ::Policy, ::Role,
#   ::User, or ::UserToGroupEdition resources are used.
# DisableRollback: boolean
#   mutually exclusive rel w/ OnFailure
# OnFailure: optional string, DO_NOTHING | [ROLLBACK] | DELETE
#   mutually exclusive rel w/ DisableRollback
# NotificationARNs: list, SNS topics to notify on event
# Parameters: optional list of dicts
#   {
#       'ParameterKey': 'string',
#       'ParameterValue': 'string',
#       'UsePreviousValue': True|False
#   },
# ResourceTypes: optional list, AWS::service_name::* or AWS::service_name::resource_logical_ID
#   can pass restricted values if iam policies demand it.
# RoleARN: optional string, min len of 20. max len of 2048.
#   role for cloudformation to assume on the user's behalf. (even) if a user only has
#   permissions to cloudformation, cloudformation can assume this role and use it
#   to create resources.
# StackPolicyBody: optional string, max 16384
#   mutually exclusive rel w/ StackPolicyURL
#   use this to protect specific resources from destructive updates. as in, it can
#   prevent thoughts like: CLOUDFORMATION, IF YOU TEAR DOWN THAT RDS OVER THIS
#   UPDATE, I WILL ******* STAB MYSELF.
#   http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/protect-stack-resources.html
# StackPolicyURL: optional string. StackPolicyBody too long? put it on S3.
# Tags: optional list of dicts, { 'Key': 'string', 'Value': 'string' }

HELP = {
    'stackset': 'Use a stackset other than "Default".',
    'zappa': '(Optional) Name of the zappa environment to deploy.'
}

@click.group()
@click.option('--debug/--no-debug', default=False)
def cli(debug):
    if debug:
        click.echo('Debug mode is on')
        logger.setLevel(logging.DEBUG)
        logging.getLogger('botocore').setLevel(logging.CRITICAL) # too much noise.

@cli.command()
@click.argument('specfile', type=click.Path())
@click.option('-s', '--stackset', 'stackset_name', type=click.STRING, default=None, help=HELP['stackset'])
@click.option('-z', '--zappa', 'zappa_env', type=click.STRING, default="", help=HELP['zappa'])
def deploy(specfile, stackset_name, zappa_env):
    '''Creates or Updates a set of CloudFormation stacks as defined in the specfile'''
    ss = parse_specfile(specfile, stackset_name)

    if not ss:
        sys.exit(1)

    r = ss.deploy()
    if r:
        logger.info('Outputs: {}'.format(ss.outputs))
    else:
        logger.error("The deploy process reported errors. Please check the logs or the AWS console.")
        sys.exit(1)

    zsfilepath = os.path.join(os.path.basename(specfile),'zappa_settings.json', zappa_env)
    if zappa and os.path.isfile(zsfilepath):
        deploy_zappa(zsfilepath, ss.outputs)

    logger.info('Completed without error.')
    sys.exit(0)

@cli.command()
@click.argument('specfile', type=click.File())
@click.option('-s', '--stackset', 'stackset_name', type=click.STRING, default=None, help=HELP['stackset'])
def delete(specfile, stackset_name):
    '''Deletes a set of CloudFormation stacks as defined in the specfile'''
    ss = parse_specfile(specfile, stackset_name)

    if not ss:
        sys.exit(1)

    r = ss.delete()
    if r == 0:
        logger.error("The delete process reported errors. Please check the logs or the AWS console.")
    if r < 1 and r > 0:
        logger.warning("{}% of stacks failed to delete properly. Please check the logs or the AWS console.".format(int((1.0-r)*100)))
        sys.exit(1)

    logger.info('Completed without error.')
    sys.exit(0)


### zappa
def deploy_zappa(zsfilepath, stackset, zappa_env):
    logger.debug('zappa: reading settings file')
    with open(zsfilepath, 'r') as f:
        j = f.read()

    logger.debug('zappa: parsing settings file')
    zs = json.loads(j)

    # replace refs with outputs.
    logger.debug('zappa: replacing refs in settings file')
    zsidx = reverse_index(zs)
    for i in get_refs(zs):
        for k in zsidx[i]:
            zs[k] = stackset.get_output(i)
            logger.debug('zappa: updated {} to {} ({})'.format(k, zs[k], i))

    # make a copy of the original json file.
    backup = "{}.orig".format(zsfilepath)
    logger.debug('zappa: creating backup copy of the zappa_settings file.')
    call(["cp",zsfilepath,backup])

    # write a new json file with refs replaced.
    logger.debug('zappa: writing live zappa_settings file.')
    with open(zsfilepath,'w') as f:
        f.write(json.dumps(zs))

    # run zappa, catch all exceptions
    logger.debug('zappa: here goes nothing...')
    try:
        call("zappa","deploy",zappa_env)
    except Exception as e:
        logger.error('zappa deploy {} failed!'.format(zappa_env))
        logger.error(e.message)

    # copy the new json file to a new name with a timestamp or stg
    dt = datetime.now().isoformat().replace(':','').split('.')[0]
    archivename = os.path.join(os.path.dirname(zsfilepath),'zappa_settings.{}.json'.format(dt))
    logger.debug('zappa: archiving the live settings file to {}'.format(archivename))
    call(["cp", zsfilepath, archivename])

    # overwrite the zappa_settings.json file with the original
    logger.debug('zappa: archiving the live settings file to {}'.format(archivename))
    call(['mv', '-f', backup, zsfilepath])

### helpers
def get_refs(haystack,ref_prefix='cfnbotOutputs.'):
    '''provides a list of refs present in a dict. optional string prefix.'''
    r = []
    if isinstance(haystack,list):
        for v in haystack:
            tv = type(v)
            if isinstance(v,list) or isinstance(v,dict):
                r += get_refs(v,ref_prefix)
            if isinstance(v,str) and v.startswith(ref_prefix):
                r.append(v)
    if isinstance(haystack,dict):
        for k,v in haystack.items():
            tv = type(v)
            if isinstance(v,list) or isinstance(v,dict):
                r += get_refs(v,ref_prefix)
            if isinstance(v,str) and v.startswith(ref_prefix):
                r.append(v)
    return list(set(r))

def reverse_index(d):
    '''provides a list of keys for each value found in a dict'''
    r = defaultdict(list)
    for k,v in d.items():
        r[v].append(k)
    return r

### parsers
def parse_specfile(specfile, stackset_name):
    try:
        with open(specfile,'r') as f:
            spec = yaml.load(f.read())
    except Exception as e:
        logger.error("Couldn't read the YAML provided. Does it pass linting? Am I broken?")
        logger.debug(e.message)
        sys.exit(1)

    ss = None
    if is_n_stacksets(spec):
        if type(stackset_name) is str and stackset_name not in list(spec.keys()):
            logger.error('{} not found in spec.keys(): {}'.format(stackset_name, spec.keys()))
            return None
        ssn = stackset_name if stackset_name else StackSet().name
        ss = parse_stackset(spec[ssn],ssn)
        ss.stacks = [parse_stack(s, ss.name if ss.name != 'Default' else None) for s in spec[ss.name]['Stacks']]
    elif is_one_stack(spec):
        ss = StackSet(stacks=[{list(spec.keys())[0]: parse_stack(spec)}])
    elif is_multiple_stacks(spec):
        ss = StackSet(stacks=[{k: parse_stack(spec[k])} for k in list(spec.keys())])

    if not ss:
        logger.error("The YAML document was parsed properly, but did not appear to be in any known format.")
        return None

    logger.debug('Specfile parsed, moving on...')
    return ss


def parse_stackset(snip, name):
    '''Create a StackSet object out of a spec snippet'''
    ss = StackSet(name=name)
    keys = list(snip.keys())
    if 'TemplateBucket' in keys:
        ss.template_bucket = snip['TemplateBucket']
    return ss

def parse_stack(snip, prefix=None, sep='-'):
    '''Create a Stack object out of a spec snippet'''
    n = snip['StackName'] if not prefix else "{p}{sep}{sn}".format(p=prefix,sep=sep,sn=snip['StackName'])
    s = Stack(name=n, template_path=snip['TemplatePath'])
    for k in snip.keys():
        if k in ['StackName', 'TemplatePath']:
            continue
        if k == 'Parameters':
            s.parameters = snip[k]
        if k == 'OutputChecks':
            s.output_checks = snip[k]
        if k == 'Tags':
            s.tags = snip[k]
        if k == 'Settings':
            s.settings = snip[k]
        if k == 'TemplateBucket':
            s.template_bucket = snip[k]
    return s

### checks
def is_one_stack(spec):
    '''
    One top key only, which can't be "Default" or "Stacks". Must contain a TemplatePath.
    ---
    SomeAppBucket:
        TemplatePath: 'bucket.yml'
        Parameters: [...]
    '''
    topkeys = spec.keys()
    if len(topkeys) != 1:
        logger.debug('is_one_stack: More than one top key, skipping.')
        return False
    if topkeys[0] in ['Default','Stacks']:
        logger.debug('is_one_stack: Top key is either "Default" or "Stacks".')
        return False
    return True

def is_multiple_stacks(spec):
    '''
    One top key only, "Stacks", and its value must be a list. For example:
    ---
    Stacks:
        - SomeAppBucketRole:
            TemplatePath: cfn/iam_role.yml
            Parameters: [...]
        - SomeAppBucket:
            TemplatePath: cfn/s3bucket_with_roles.yml
            StackName: SomeAppBucket
            Parameters: [...]
    '''

    if list(spec.keys())[0] != 'Stacks':
        logger.debug('is_multiple_stacks: Top key is not "Stacks"')
        return False
    if type(spec['Stacks']) != list:
        logger.debug('is_multiple_stacks: "Stacks" is not a list.')
        return False
    return True

def is_n_stacksets(spec):
    '''
    ALL THE THINGS. Need a Default in there somewhere, and it needs a Stacks list.
    ---
    Dev:
      StackNamePrefix: Dev
      CredentialProfile: default
      Stacks:
        - SomeAppBucketLambdaRole
            TemplatePath: cfn/iam_role_dev.yml
    Default:
        Stacks:
            - SomeAppBucketRole:
                TemplatePath: cfn/iam_role.yml
                Parameters: [...]
            - SomeAppBucket:
                TemplatePath: cfn/s3bucket_with_roles.yml
                StackName: SomeAppBucket
                Parameters: [...]
    '''
    if 'Default' not in spec.keys():
        logger.debug('is_n_stacksets: "Default" is not in top keys.')
        return False
    if 'Stacks' not in spec['Default']:
        logger.debug('is_n_stacksets: "Stacks" is not in top keys.')
        return False
    if type(spec['Default']['Stacks']) is not list:
        logger.debug('is_n_stacksets: "Stacks" is not a list.')
        return False
    if len(spec['Default']['Stacks']) == 0:
        logger.debug('is_n_stacksets: "Stacks" is empty.')
        return False
    return True

if __name__ == '__main__':
    cli()
