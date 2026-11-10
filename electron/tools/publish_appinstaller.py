"""Publish immutable MSIX bytes before conditionally promoting App Installer XML."""

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

from electron.private.appinstaller import LIMIT, NAMESPACE, package_identity, uri, version
from electron.tools.publish_s3 import S3Publisher, add_s3_arguments, publisher_from_environment
from electron.tools.publish_update import filename


def open_regular(path):
    if Path(path).is_symlink():
        raise ValueError('Publication inputs require regular files')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    source = os.fdopen(descriptor, 'rb')
    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
        source.close()
        raise ValueError('Publication inputs require regular files')
    return source


def public_name(address, extension, allow_http_loopback):
    uri(address, allow_http_loopback)
    encoded = urlsplit(address).path.rsplit('/', 1)[-1]
    name = filename(unquote(encoded, errors='strict'))
    canonical = re.sub(r'%[0-9a-fA-F]{2}', lambda match: match[0].upper(), encoded)
    if quote(name, safe='-._~') != canonical or not name.lower().endswith(extension):
        raise ValueError('Invalid published App Installer filename')
    return name


def stage(descriptor, package, output, allow_http_loopback=False):
    with open_regular(descriptor) as source:
        data = source.read(LIMIT + 1)
    if len(data) > LIMIT or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', data.decode('utf-8-sig')):
        raise ValueError('Invalid App Installer descriptor')
    root = ET.fromstring(data)
    ns = '{' + NAMESPACE + '}'
    allowed = {ns + name for name in ('MainPackage', 'UpdateSettings', 'UpdateUris', 'RepairUris')}
    if (root.tag != ns + 'AppInstaller' or any(child.tag not in allowed for child in root)
            or any(sum(child.tag == tag for child in root) > 1 for tag in allowed)):
        raise ValueError('Publication requires a single-package App Installer descriptor')
    main = root.find(ns + 'MainPackage')
    if main is None:
        raise ValueError('App Installer requires a main package')
    for name in ('Update', 'Repair'):
        group = root.find(ns + name + 'Uris')
        if group is not None:
            values = [child.text for child in group]
            if (group.attrib or len(values) > 10 or len(set(values)) != len(values)
                    or any(child.tag != ns + name + 'Uri' or child.attrib or len(child) for child in group)):
                raise ValueError('Invalid App Installer fallback URIs')
            for value in values:
                uri(value, allow_http_loopback)
    version(root.attrib.get('Version'))
    channel = public_name(root.attrib.get('Uri'), '.appinstaller', allow_http_loopback)
    name = public_name(main.attrib.get('Uri'), '.msix', allow_http_loopback)
    if channel.casefold() == name.casefold():
        raise ValueError('Publication filename collision')
    target = output / name
    with open_regular(package) as source, target.open('wb') as destination:
        shutil.copyfileobj(source, destination, 1024**2)
    expected = {**package_identity(target), 'Uri': main.attrib['Uri']}
    if main.attrib != expected:
        raise ValueError('App Installer identity differs from the supplied MSIX')
    (output / channel).write_bytes(data)
    return channel, [target]


class AppInstallerPublisher(S3Publisher):
    def content_type(self, path):
        return 'application/appinstaller' if path.suffix.lower() == '.appinstaller' else 'application/msix'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    add_s3_arguments(parser)
    args = parser.parse_args()
    try:
        publisher = publisher_from_environment(args, AppInstallerPublisher)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            channel, uploads = stage(args.descriptor, args.package, output, args.allow_http_loopback)
            publisher.publish(output, channel, uploads)
        print('APPINSTALLER_PUBLISHED')
    except Exception:
        print('APPINSTALLER_PUBLICATION_FAILED', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
