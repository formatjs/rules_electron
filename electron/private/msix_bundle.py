"""Deterministic embedded MSIX bundles; payload packages remain byte-identical."""

import io
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

from electron.private.appinstaller import FOUNDATION, package_identity, read_package_manifest, version
from electron.private.msix import PackageZip, payload_name, xml

BUNDLE = 'http://schemas.microsoft.com/appx/2013/bundle'
MANIFEST = 'AppxMetadata/AppxBundleManifest.xml'


def manifest_shape(node):
    attributes = dict(node.attrib)
    if node.tag == '{' + FOUNDATION + '}Identity':
        attributes.pop('ProcessorArchitecture', None)
    text = node.text or ''
    return (node.tag, sorted(attributes.items()), text if text.strip() else '',
            [(manifest_shape(child), child.tail if (child.tail or '').strip() else '') for child in node])


def create_bundle(packages, output, package_names=None, bundle_version=''):
    names, members, architectures = package_names or {}, [], set()
    common, shape = None, None
    if not packages:
        raise ValueError('MSIX bundle requires application packages')
    for source in packages:
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError('MSIX bundle inputs require regular package files')
        identity = package_identity(source)
        root = read_package_manifest(source)
        architecture = identity['ProcessorArchitecture']
        if architecture in architectures:
            raise ValueError('MSIX bundle has duplicate application architecture')
        architectures.add(architecture)
        candidate = {key: identity[key] for key in ('Name', 'Publisher', 'Version')}
        candidate_shape = manifest_shape(root)
        if common is not None and (candidate != common or candidate_shape != shape):
            raise ValueError('MSIX bundle manifests must match except ProcessorArchitecture')
        common, shape = candidate, candidate_shape
        identifier = root.find('{' + FOUNDATION + '}Identity')
        resource = root.find('{' + FOUNDATION + '}Properties/{' + FOUNDATION + '}ResourcePackage')
        if identifier.attrib.get('ResourceId') or resource is not None and (resource.text or '').strip().lower() == 'true':
            raise ValueError('MSIX bundle currently accepts application packages only')
        name = names.get(architecture, 'package-' + architecture + '.msix')
        payload_name(name)
        if '/' in name or not name.lower().endswith('.msix'):
            raise ValueError('Bundle package names must be root-level MSIX filenames')
        resources = root.find('{' + FOUNDATION + '}Resources')
        values = []
        if resources is not None:
            for item in resources:
                attributes = {key.rsplit('}', 1)[-1]: value for key, value in item.attrib.items()}
                if item.tag != '{' + FOUNDATION + '}Resource' or not set(attributes).issubset({'Language', 'Scale', 'DXFeatureLevel'}):
                    raise ValueError('Unsupported MSIX bundle resource qualifier')
                values.append(attributes)
        members.append((name, source, identity, values))
    if not set(names).issubset(architectures):
        raise ValueError('Bundle package_names contains an unused architecture')
    if len({name.casefold() for name, *_ in members}) != len(members):
        raise ValueError('Bundle package filename collision')
    root = ET.Element('Bundle', xmlns=BUNDLE, SchemaVersion='5.0',
                      **{'xmlns:b4': 'http://schemas.microsoft.com/appx/2018/bundle',
                         'xmlns:b5': 'http://schemas.microsoft.com/appx/2019/bundle',
                         'IgnorableNamespaces': 'b4 b5'})
    ET.SubElement(root, 'Identity', **{**common, 'Version': version(bundle_version or common['Version'])})
    container = ET.SubElement(root, 'Packages')
    with Path(output).open('wb') as destination:
        writer = PackageZip(destination)
        for name, source, identity, resources in sorted(members):
            with source.open('rb') as package:
                offset, size = writer.add(name, package, 'application/vnd.ms-appx', hashed=False, compressed=False)
            entry = ET.SubElement(container, 'Package', Type='application', Version=identity['Version'],
                                  Architecture=identity['ProcessorArchitecture'], FileName=name,
                                  Offset=str(offset), Size=str(size))
            if resources:
                group = ET.SubElement(entry, 'Resources')
                for attributes in resources:
                    ET.SubElement(group, 'Resource', **attributes)
        writer.add(MANIFEST, io.BytesIO(xml(root)), 'application/vnd.ms-appx.bundlemanifest+xml')
        writer.close()


if __name__ == '__main__':
    create_bundle(output=sys.argv[2], **json.loads(Path(sys.argv[1]).read_text()))
