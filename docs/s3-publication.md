# S3 update publication

`@rules_electron//electron/tools:publish_s3` uploads verified update feeds using
AWS Signature Version 4. Run it explicitly from the BB Linux release workflow.
Artifact builds stay offline; ordinary CI never publishes releases.

```sh
bazel run --config=bb-workflow @rules_electron//electron/tools:publish_s3 -- \
  --feed "$windows_arm64_feed" --channel latest.yml \
  --destination https://sample-updates.s3.us-west-2.amazonaws.com/desktop/windows/arm64/ \
  --region us-west-2
```

Supply `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and optional `AWS_SESSION_TOKEN`
privately to the release process. Flags `--access-key-env`, `--secret-key-env` and
`--session-token-env` select different environment variable names. Credentials
never enter rule attributes, app configuration or artifact actions. The client
uses the pinned Python runtime and standard library; it invokes no AWS CLI,
credential discovery, metadata service or host SDK.

`--destination` names the complete bucket/prefix URL. Choose the correct regional
API endpoint explicitly; redirects fail without forwarding credentials. Custom
S3-compatible HTTPS endpoints work only if they implement signed HEAD/GET/PUT and
the required conditional writes. The public updater URL may use a separate CDN;
the uploaded object keys must match its configuration.

Before requests, the shared publisher snapshots the feed and verifies artifact
SHA-512/size and external blockmaps. Each request signs its payload's SHA-256,
host, date, session token and conditional headers, following
[AWS's signature calculation](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sig-v4-header-based-auth.html).
Unicode names are percent-encoded; repeated prefix slashes remain significant.
Uploads stream from files with bounded memory.

Payloads/maps use `If-None-Match: *`. Existing objects must download with identical
bytes before reuse. Channel metadata uploads last using a strong ETag and
`If-Match`, or `If-None-Match: *` for a new channel. This follows
[S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).
A concurrent write, HTTP 409/412, redirect or other failed request stops promotion;
rerun after resolving the conflict. Serialize intended channel promotions.

Single-part uploads up to 5 GiB per object are supported. Multipart uploads,
ACL/storage-class/encryption overrides, credential refresh and live cloud-policy
validation remain open. Bucket defaults own those storage policies. Exceptions
and service bodies are withheld from command output.

Validation is pending. BB tests run AWS's documented GET/PUT signature vectors
and the public executable against a signature-verifying loopback server. They
exercise session tokens, Unicode keys, repeated slashes, exact bytes/order,
identical retry, concurrent channels, HTTP 409, redirects, wrong signatures,
corrupt feeds and the single-part size boundary. These tests do not establish
live AWS or other provider interoperability.
