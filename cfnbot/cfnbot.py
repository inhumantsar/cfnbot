import boto3
import yaml
import json
import logging
import os
import inspect
import random
import botocore.exceptions


logger = logging.getLogger()
cfn = boto3.client('cloudformation')

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

### checks
def is_over_50kb(path):
    '''Checks to see if the cfn template is too big to send via the API'''
    if not os.path.isfile(path):
        raise Exception('Path specified does not lead to a valid file: {}'.format(path))
    if os.path.getsize(path) > 51200:
        return True
    return False

def stack_exists(stackname):
    '''Returns true if a stack exists, false if it doesn't, barfs if things explode.'''
    try:
        cfn.describe_stacks(StackName=stackname)
        logger.info('No cfn kaboom means the stack exists.')
        return True
    except Exception as e:
        logger.info(e)
        logger.info('cfn kaboomed, stack does not already exist.')
        return False
    # except Exception as e:
    #     logger.error('cfn kaboomed in a bad way. raising exception...')
    #     raise(e)
    else:
        # ??? fuck it.
        if random.randrange(0,1,0.1) > .5:
            return True # heads
        return False # tails

### helpers
def clean_path(path):
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    path = os.path.realpath(path)
    path = os.path.abspath(path)
    return path

def upload_template(path, bucket):
    k = os.path.basename(path)
    o = boto3.resource('s3').Object(bucket,k).put_object(Body=open(path,'r'))
    return boto3.client('s3').generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': k},
        ExpiresIn=120
    )


### the meat
class Outputs:
    def __init__(self): pass
    def get(self, k): return getattr(self, k, None)
    def add(self, k, v):
        if getattr(self, k, None):
            raise Exception('Output {} already registered with this stack.'.format(k))
        setattr(self, k, v)


class Stack:
    def __init__(self, name, template_path, template_bucket=None, parameters=None, output_checks=None, tags=None, settings=None):
        self.name = name
        self.template_path = template_path
        self.template_bucket = template_bucket
        self.parameters = parameters if parameters else {}
        self.output_checks = output_checks if output_checks else []
        self.outputs = Outputs()
        self.tags = tags if tags else []
        self.settings = settings if settings else {}
        self.status = None

    def deploy(self,stackset=None):
        # adopt the global settings as needed...
        self.name = "{}-{}".format(stackset.name, self.name) if stackset else self.name
        if stackset and stackset.template_bucket and not self.template_bucket:
            self.template_bucket = stackset.template_bucket

        # fetch parameter outputs
        if stackset:
            for k,v in self.parameters.items():
                if v.startswith('cfnbotOutputs'):
                        v = stackset.get_output(v)

        # create or update
        if stack_exists(self.name):
            try:
                cfn.update_stack(**self.generate_cfn_args())
                waiter_status = 'stack_update_complete'
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Message'] != "No updates are to be performed.":
                    raise(e)
                logger.info("No updates required for {}".format(self.name))
                waiter_status = None
            except Exception as e:
                logger.error('create_stack kaboomed.')
                raise(e)
        else:
            try:
                cfn.create_stack(**self.generate_cfn_args())
                waiter_status = 'stack_create_complete'
            except Exception as e:
                logger.error('create_stack kaboomed.')
                raise(e)

        # wait for status
        if waiter_status:
            waiter = cfn.get_waiter(waiter_status)
            waiter.wait(StackName=self.name)

    def generate_cfn_args(self):
        '''CloudFormation API arguments for a stack.'''
        args = {}
        args['StackName'] = self.name

        # check template size, upload if necessary
        if is_over_50kb(self.template_path):
            logger.info('{} is larger than 51,200 bytes, uploading to S3...')
            if not self.template_bucket:
                raise Exception('{} cannot be uploaded to S3 because a TemplateBucket was not specified')
            args['TemplateURL'] = upload_template(self.template_path, self.template_bucket)
            logger.info('Template uploaded. Presigned url valid for 120s: {}'.format(args['TemplateURL']))
        else:
            with open(self.template_path,'r') as f:
                args['TemplateBody'] = f.read()

        # parse parameters
        args['Parameters'] = [{'ParameterKey': k, 'ParameterValue': v} for k, v in self.parameters.items()]

        # parse tags
        args['Tags'] = []
        for k,v in self.tags.items():
            if type(k) is not str:
                raise Exception('Tag key must be a string. Found: {}'.format(type(k)))
            if type(v) is not str:
                raise Exception('Tag value must be a string. Found: {}'.format(type(v)))
            logger.debug('Adding tag: {}: {}'.format(k,v))
            args['Tags'].append({'Key': k, 'Value': v})

        # parse extra settings
        for k, v in self.settings.items():
            if k in args.keys():
                raise Exception('{} already present in CloudFomration API arguments list! Cowardly refusing to overwrite it.')
            logger.debug('Adding extra setting: {}: {}'.format(k,v))
            args[k] = v
        return args



class StackSet:
    def __init__(self, name='Default', profile='default', stacks=None):
        self.name = name
        self.profile = profile
        self.stacks = stacks if stacks else []

    def deploy(self):
        '''Creates or Updates all stacks in the stackset'''
        cfnargs = []
        for s in self.stacks:
            # update where necessary
            s.deploy(self)
        return cfnargs

    def get_output(self, value):
        '''
        Checks stack parameters to see if the value refers to another stack's output
        and returns it if it does so properly.
        '''
        _, stackname, key = value.split('.')
        for s in self.stacks:
            if s.name == stackname:
                r = s.outputs.get(key)
                if r: return r

        # raise if not found, because we don't provide defaults to output refs
        raise Exception('Unable to find an output named "{}" in a stack named {}'.format(key, stackname))
