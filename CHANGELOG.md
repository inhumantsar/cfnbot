## 1.0.0a
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
