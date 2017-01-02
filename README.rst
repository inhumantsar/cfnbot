cfnbot
======

Make managing CloudFormation stacks a little friendlier.

**Still very much a work in progress**

Install
~~~~~~~

::

    $ pip install cfnbot

Usage
~~~~~

::

    # First, write a specfile. See `example_specfile.yml` for more info.
    $ cfnbot deploy [--debug] /path/to/specfile.yml [--stackset <name>]
    $ cfnbot delete [--debug] /path/to/specfile.yml [--stackset <name>]

Specfile Formats
~~~~~~~~~~~~~~~~

Single Stack
^^^^^^^^^^^^

One top key only, which can't be "Default" or "Stacks". Must contain a
TemplatePath.

::

    ---
    SomeAppBucket:
        TemplatePath: 'bucket.yml'
        Parameters: [...]

Multiple Stacks
^^^^^^^^^^^^^^^

One top key only, "Stacks", and its value must be a list. For example:

::

    ---
    Stacks:
        - SomeAppBucketRole:
            TemplatePath: cfn/iam_role.yml
            Parameters: [...]
        - SomeAppBucket:
            TemplatePath: cfn/s3bucket_with_roles.yml
            StackName: SomeAppBucket
            Parameters: [...]

Stack Sets
^^^^^^^^^^

ALL THE THINGS. Need a Default in there somewhere, and it needs a Stacks
list.

::

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
