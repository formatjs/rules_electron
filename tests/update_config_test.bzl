"""Reject mixed providers and unsafe public object-storage addresses."""

load("//electron:update.bzl", "electron_update_config")

def _impl(ctx):
    subject = ctx.attr.subject
    if type(subject) == "list":
        subject = subject[0]
    rejected = AnalysisFailureInfo in subject and any([
        ctx.attr.message in cause.message
        for cause in subject[AnalysisFailureInfo].causes.to_list()
    ])
    return [AnalysisTestResultInfo(success = rejected, message = "Expected provider configuration rejection: " + ctx.attr.message)]

_rejection_test = rule(
    implementation = _impl,
    attrs = {
        "subject": attr.label(mandatory = True, cfg = analysis_test_transition(settings = {"//command_line_option:allow_analysis_failures": "True"})),
        "message": attr.string(mandatory = True),
    },
    analysis_test = True,
    test = True,
)

def update_config_tests(name):
    """Exercise provider boundaries during real Bazel analysis."""
    cases = [
        ("mixed", {"owner": "example"}, "cannot use generic/GitHub options"),
        ("region", {"region": ""}, "requires an explicit region"),
        ("name", {"bucket": "sample/escape"}, "DNS-compatible"),
        ("path", {"path": "desktop/../escape"}, "normalized URL-safe segments"),
        ("endpoint", {"endpoint": "https://user:secret@example.invalid"}, "without credentials"),
        ("acceleration", {"bucket": "sample.updates", "accelerate": True}, "dotted bucket"),
        ("spaces", {"provider": "spaces", "space_name": "sample-updates"}, "S3-only options"),
        ("generic", {"provider": "generic", "url": "https://updates.example.invalid/"}, "Object storage options require"),
    ]
    for suffix, overrides, message in cases:
        subject = name + "_" + suffix + "_subject"
        options = dict(provider = "s3", bucket = "sample-updates", region = "us-west-2", cache_name = "sample-updater")
        options.update(overrides)
        electron_update_config(name = subject, tags = ["manual"], **options)
        _rejection_test(name = name + "_" + suffix, subject = ":" + subject, message = message)
