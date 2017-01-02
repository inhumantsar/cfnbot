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
        logger.debug('File is over the AWS limit of 51,200 bytes.')
        return True
    return False

def stack_exists(stackname):
    '''Returns true if a stack exists, false if it doesn't, barfs if things explode.'''
    try:
        cfn.describe_stacks(StackName=stackname)
        logger.debug('{} already exists.'.format(stackname))
        return True
    except Exception as e:
        # remember to raise on actual errors
        if 'Error' not in e.response.keys():
            raise(e)
        if e.response['Error']['Message'] != 'Stack with id {} does not exist'.format(stackname):
            raise(e)
        logger.debug("describe_stacks sez that the stack doesn't exist.")
        return False

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

def maybe_log_an_error(e):
    '''log an error, maybe'''
    try:
        logger.error(e.response['Error']['Message'])
        return e.response['Error']['Message']
    except:
        return None

def _describe_stacks(n):
    try:
        stacks = cfn.describe_stacks(StackName=n)['Stacks']
    except Exception as e:
        logger.error('describe_stack failed while looking for outputs.')
        maybe_log_an_error(e)
        return None

    if len(stacks) > 1 or len(stacks) == 0:
        logger.error('describe_stack returned too many stacks. i don\'t know what to do with all these.')
        raise Exception('describe_stack returned too many stacks')

    return stacks

def _waiter(waiter_status, stackname):
    try:
        waiter = cfn.get_waiter(waiter_status)
        waiter.wait(StackName=stackname)
        logger.debug('Success! {} obtained.'.format(waiter_status))
    except Exception as e:
        logger.debug("The {} waiter reported an error.".format(waiter_status))
        return False
    return True


### the meat
class Stack:
    def __init__(self, name, template_path, template_bucket=None, parameters=None, output_checks=None, tags=None, settings=None):
        self.name = name
        self.template_path = template_path
        self.template_bucket = template_bucket
        self.parameters = parameters if parameters else {}
        self.output_checks = output_checks if output_checks else []
        self.tags = tags if tags else []
        self.settings = settings if settings else {}
        self._status = None
        self._outputs = None

    @property
    def status(self):
        if self._status:
            return self._status

        stacks = _describe_stacks(self.name)
        if not stacks:
            self._status = None

        s = stacks[0]
        if 'StackStatus' not in s.keys():
            logger.warning("describe_stacks didn't return a StackStatus, but also didn't fail.")
            self._status = None
        else:
            self._status = s['StackStatus']

        return self._status


    @property
    def outputs(self):
        if not self.output_checks or len(self.output_checks) == 0:
            logger.debug('No output_checks specified.')
            return []

        if self._outputs:
            return self._outputs

        stacks = _describe_stacks(self.name)
        if not stacks:
            logger.warning('describe_stacks returned no stacks at all.')
            return None

        s = stacks[0]
        if 'Outputs' not in s.keys():
            logger.error('No Outputs section found in the stack output. Details in debug output.')
            logger.debug(s)
            return None

        self._outputs = {i['OutputKey']: i['OutputValue'] for i in s['Outputs']}
        return self._outputs

    def refresh_status(self,outputs=True,Status=True):
        if status and self._status:
            logger.debug('refreshing status...')
            o = copy(self._status)
            self._status = None
            return self.status

    def refresh_outputs(self,outputs=True,Status=True):
        if outputs and self._outputs:
            logger.debug('refreshing outputs...')
            o = copy(self._outputs)
            self._outputs = None
            return self.outputs

    def delete(self):
        '''Burn it to the ground. Returns True/False.'''
        if not stack_exists(self.name):
            logger.debug("stack_exists reports that {} doesn't exist. Skipping delete.".format(self.name))
            return True

        try:
            cfn.delete_stack(StackName=self.name)
            waiter_status='stack_delete_complete'
        except Exception as e:
            logger.error('delete_stack failed on {}'.format(self.name))
            maybe_log_an_error(e)
            return False

        return _waiter(waiter_status, self.name)


    def deploy(self,stackset=None):
        '''
        Perform a Create or an Update on the stack. If a stackset is provided, its
        bits will be incorporated automagically. Returns True/False.
        '''
        # adopt the global settings as needed...
        if stackset:
            if stackset.name != "Default":
                self.name = "{}-{}".format(stackset.name, self.name)
                logger.info('Stack name updated to {}'.format(self.name))
            if stackset.template_bucket and not self.template_bucket:
                self.template_bucket = stackset.template_bucket
                logger.debug('Inherited template_bucket: {}'.format(self.template_bucket))

        # fetch parameter outputs
        if stackset:
            for k,v in self.parameters.items():
                if v.startswith('cfnbotOutputs'):
                    logger.debug('output reference found, checking stackset for {}.'.format(v))
                    o = stackset.get_output(v)
                    if o:
                        logger.debug('value for {} found: {}'.format(v,o))
                        self.parameters[k] = o
                        logger.debug('Parameter "{}" updated.'.format(k))

        # create or update
        if stack_exists(self.name):
            waiter_status = None
            try:
                cfn.update_stack(**self.generate_cfn_args())
                logger.info('Updating {}...'.format(self.name))
                waiter_status = 'stack_update_complete'
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Message'] != "No updates are to be performed.":
                    maybe_log_an_error(e)
                logger.info("No updates required for {}".format(self.name))
                return True
            except Exception as e:
                logger.error('update_stack failed.')
                maybe_log_an_error(e)
                return False
        else:
            try:
                cfn.create_stack(**self.generate_cfn_args())
                logger.info('Creating {}...'.format(self.name))
                waiter_status = 'stack_create_complete'
            except Exception as e:
                logger.error('create_stack failed! hopefully for good reasons.')
                maybe_log_an_error(e)
                return False

        # wait for status
        return _waiter(waiter_status, self.name)

    def generate_cfn_args(self):
        '''CloudFormation API arguments for a stack.'''
        args = {}
        args['StackName'] = self.name

        # check template size, upload if necessary
        if is_over_50kb(self.template_path):
            logger.warning('{} is larger than 51,200 bytes, uploading to S3...')
            if not self.template_bucket:
                raise Exception('{} cannot be uploaded to S3 because a TemplateBucket was not specified')
            args['TemplateURL'] = upload_template(self.template_path, self.template_bucket)
            logger.debug('Template uploaded. Presigned url valid for 120s: {}'.format(args['TemplateURL']))
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
        '''Creates or Updates all stacks in the stackset. Returns (successes/total)'''
        for s in self.stacks:
            if not s.deploy(self):
                return False
        return True

    def delete(self):
        '''Burns all stacks in the stackset. Returns (successes/total)'''
        r = []
        for s in self.stacks:
            r.append(s.delete())
        return float(len([i for i in r if i])) / float(len(r))

    def get_output(self, value):
        '''
        Checks stack parameters to see if the value refers to another stack's output
        and returns it if it does so properly.
        '''
        _, stackname, key = value.split('.')
        logger.debug('Searching {} stacks for {}.{}'.format(len(self.stacks), stackname, key))
        for s in self.stacks:
            if s.name == stackname:
                if s.outputs and key in s.outputs.keys():
                    logger.debug('Found output reference: {}'.format(s.outputs[key]))
                    return s.outputs[key]

        # raise if not found, because we don't provide defaults to output refs
        raise Exception('Unable to find an output named "{}" in a stack named {}'.format(key, stackname))
