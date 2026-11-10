"""Reject portable launchers where electron-updater expects installers."""

load("//electron:portable.bzl", "ElectronPortableInfo")
load("//electron:update.bzl", "electron_update_feed")

def _fixture_impl(ctx):
    artifact = ctx.actions.declare_file(ctx.label.name + ".exe")
    ctx.actions.write(artifact, "analysis fixture")
    return [DefaultInfo(files = depset([artifact])), ElectronPortableInfo(artifact = artifact)]

_fixture = rule(implementation = _fixture_impl)

def _test_impl(ctx):
    subject = ctx.attr.subject
    if type(subject) == "list":
        subject = subject[0]
    rejected = AnalysisFailureInfo in subject and any([
        "Portable executables cannot be used as electron-updater installers" in cause.message
        for cause in subject[AnalysisFailureInfo].causes.to_list()
    ])
    return [AnalysisTestResultInfo(success = rejected, message = "Portable update feed must fail during analysis")]

_feed_test = rule(
    implementation = _test_impl,
    attrs = {"subject": attr.label(mandatory = True, cfg = analysis_test_transition(settings = {"//command_line_option:allow_analysis_failures": "True"}))},
    analysis_test = True,
    test = True,
)

def portable_feed_test(name):
    """Check the typed release boundary without building a Windows payload."""
    _fixture(name = name + "_portable", tags = ["manual"])
    electron_update_feed(
        name = name + "_feed",
        artifacts = {":" + name + "_portable": "portable.exe"},
        package_json = "fixtures/package.json",
        platform = "windows",
        architecture = "x64",
        release_date = "2024-01-01T00:00:00Z",
        tags = ["manual"],
    )
    _feed_test(name = name, subject = ":" + name + "_feed")
