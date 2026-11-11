"""Compose released libburnia sources without configure or host build tools."""

def _impl(ctx):
    ctx.download_and_extract(
        url = "https://deb.debian.org/debian/pool/main/libi/libisoburn/libisoburn_1.5.8.pl02.orig.tar.gz",
        sha256 = "a977b03dc3686d9fdca600458b1578f9cac2b875609bd5ec21f5ada55f20ec50",
        stripPrefix = "libisoburn-1.5.8",
    )
    for name, directory, archive, digest in [
        ("libburn", "libb", "libburn_1.5.8.orig.tar.gz", "8e24dd99f5b7cafbecf0116d61b619ee89098e20263e6f47c793aaf4a98d6473"),
        ("libisofs", "libi", "libisofs_1.5.8.pl02.orig.tar.gz", "10bd584d8f00d8091e814902b9f0a3e209f16e938f510fc23ba05f3fa469db5a"),
    ]:
        temporary = "_source_" + name
        ctx.download_and_extract(
            url = "https://deb.debian.org/debian/pool/main/%s/%s/%s" % (directory, name, archive),
            sha256 = digest,
            stripPrefix = name + "-1.5.8",
            output = temporary,
        )
        for license in ["COPYING", "COPYRIGHT", "AUTHORS"]:
            source = ctx.path(temporary + "/" + license)
            if source.exists:
                ctx.file("licenses/" + name + "/" + license, ctx.read(source), executable = False)
        ctx.rename(temporary + "/" + name, name)
        ctx.delete(temporary)
    for patch in ctx.attr.patches:
        ctx.patch(ctx.path(patch), strip = 1)
    ctx.file("BUILD.bazel", ctx.read(ctx.attr.build_file), executable = False)

xorriso_repository = repository_rule(
    implementation = _impl,
    attrs = {
        "build_file": attr.label(default = Label("//third_party:xorriso.BUILD.bazel")),
        "patches": attr.label_list(default = [
            Label("//third_party:xorriso-finder-info.patch"),
            Label("//third_party:xorriso-root-blessing.patch"),
            Label("//third_party:xorriso-volume-icon.patch"),
        ]),
    },
)
