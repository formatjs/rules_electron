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

Objects above 5 GiB use multipart uploads. `--multipart-threshold` can select a
lower byte threshold; `--part-size` defaults to 64 MiB and must be 5 MiB–5 GiB.
The client increases part size when needed to stay within 10,000 parts, following
[S3's limits](https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html).
Each part streams from a bounded file slice with its own signed hash. Completion
uses the same conditional write as a single-part upload. HTTP 200 alone is
insufficient: the client checks the completion XML and rejects embedded errors.
Failed operations abort only their own upload IDs. A retry verifies completed
objects; unfinished parts are uploaded again. Process termination before cleanup
can leave an incomplete upload for the bucket's lifecycle policy.

ACL/storage-class/encryption overrides, credential refresh and live cloud-policy
validation remain open. Bucket defaults own storage policies. Exceptions and
service bodies are withheld from command output.

The [d1a8e7f BB suite](https://formatjs.buildbuddy.io/invocation/c323eb72-4e0b-4e8a-a238-b11ac186d84a)
passed single-part publication tests. BB tests run AWS's documented GET/PUT
signature vectors and the public executable against a signature-verifying loopback server. They
exercise session tokens, Unicode keys, repeated slashes, exact bytes/order,
identical retry, concurrent channels, HTTP 409, redirects, wrong signatures,
corrupt feeds and the object-size boundary. Multipart validation is pending;
its cases include three parts with a short final part, signed query parameters,
identical-object retry, part failure, completion conflict and embedded HTTP 200
errors. These tests do not establish live AWS or other provider interoperability.
