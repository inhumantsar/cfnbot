## 1.0.0a2
- Fixed a bug in delete where I derped by coding instead of sleeping

## 1.0.0a1
- Now fails on bad deploy instead of moving on.

## 1.0.0a0
- Added delete and stack output.
- Cleaned up the debug and info level logger outputs.

## 0.1.0
### Working
- It will stand up multiple stacks one after another as defined in the specfile
  and the CloudFormation templates in.
- If run against the example_specfile from within the repo, it will stand up the
  IAM role and fail on the bucket (because someone already owns "somebucket").
  Note that these templates aren't exactly functional.

### Not working
- Delete.
- Stack output acquisition.
