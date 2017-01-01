# cfnbot

Make managing CloudFormation stacks a little friendlier.

## Current State

Janky. Output is nasty. Debug output is basically unusable. But! It works. A bit.
No delete yet. No stack output reading yet.

Working:
- It will stand up multiple stacks one after another as defined in the specfile
  and the CloudFormation templates in.
- If run against the example_specfile from within the repo, it will stand up the
  IAM role and fail on the bucket (because someone already owns "somebucket").
  Note that these templates aren't exactly functional.

### Config File Formats
#### Single Stack
One top key only, which can't be "Default" or "Stacks". Must contain a TemplatePath.

    ---
    SomeAppBucket:
        TemplatePath: 'bucket.yml'
        Parameters: [...]

#### Multiple Stacks
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

#### Stack Sets
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
