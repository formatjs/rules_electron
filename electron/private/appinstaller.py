"""Deterministic App Installer metadata from a final MSIX manifest."""

import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NAMESPACE = 'http://schemas.microsoft.com/appx/appinstaller/2021'
FOUNDATION = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'
LIMIT = 4 * 1024**2


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', value):
        raise ValueError('App Installer requires a four-component numeric version')
    if any(int(part) > 65535 for part in value.split('.')):
        raise ValueError('App Installer version component exceeds 65535')
    return value


def uri(value, allow_http_loopback):
    if not isinstance(value, str) or not value or len(value) > 2084 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('App Installer URI must be an encoded ASCII URL')
    parsed = urlsplit(value)
    loopback = allow_http_loopback and parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', '::1')
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or '\\' in value or not (parsed.scheme == 'https' or loopback)):
        raise ValueError('App Installer URI requires HTTPS without credentials, query or fragment')
    parsed.port
    return value


def package_identity(package):
    with ZipFile(package) as archive:
        entries = [info for info in archive.infolist() if info.filename == 'AppxManifest.xml']
        if len(entries) != 1 or entries[0].file_size > LIMIT or entries[0].flag_bits & 1:
            raise ValueError('MSIX requires one bounded AppxManifest.xml')
        data = archive.read(entries[0])
    decoded = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', decoded):
        raise ValueError('MSIX manifest cannot declare entities or a document type')
    root = ET.fromstring(data)
    identities = root.findall('{' + FOUNDATION + '}Identity')
    if root.tag != '{' + FOUNDATION + '}Package' or len(identities) != 1:
        raise ValueError('Invalid MSIX package identity')
    identity = identities[0].attrib
    if (not re.fullmatch(r'[A-Za-z0-9.-]{3,50}', identity.get('Name', ''))
            or not identity.get('Publisher', '').strip()
            or identity.get('ProcessorArchitecture') not in ('x64', 'arm64')):
        raise ValueError('Unsupported MSIX package identity')
    return {key: identity[key] for key in ('Name', 'Publisher', 'ProcessorArchitecture')} | {'Version': version(identity.get('Version'))}


def create_appinstaller(package, output, appinstaller_uri, package_uri, appinstaller_version='',
                        check_on_launch=True, hours_between_update_checks=24, show_prompt=False,
                        update_blocks_activation=False, automatic_background_task=False,
                        force_update_from_any_version=False, update_uris=(), repair_uris=(), allow_http_loopback=False):
    identity = package_identity(package)
    if type(hours_between_update_checks) is not int or not 0 <= hours_between_update_checks <= 255:
        raise ValueError('Update interval must be 0..255 hours')
    if update_blocks_activation and not show_prompt:
        raise ValueError('Blocking activation requires show_prompt')
    if not check_on_launch and (show_prompt or update_blocks_activation or hours_between_update_checks != 24):
        raise ValueError('Launch settings require check_on_launch')
    root = ET.Element('AppInstaller', xmlns=NAMESPACE, Version=version(appinstaller_version or identity['Version']),
                      Uri=uri(appinstaller_uri, allow_http_loopback))
    ET.SubElement(root, 'MainPackage', **identity, Uri=uri(package_uri, allow_http_loopback))
    if check_on_launch or automatic_background_task or force_update_from_any_version:
        settings = ET.SubElement(root, 'UpdateSettings')
        if check_on_launch:
            ET.SubElement(settings, 'OnLaunch', HoursBetweenUpdateChecks=str(hours_between_update_checks),
                          ShowPrompt=str(show_prompt).lower(), UpdateBlocksActivation=str(update_blocks_activation).lower())
        if automatic_background_task:
            ET.SubElement(settings, 'AutomaticBackgroundTask')
        if force_update_from_any_version:
            ET.SubElement(settings, 'ForceUpdateFromAnyVersion').text = 'true'
    for name, values in [('Update', update_uris), ('Repair', repair_uris)]:
        if len(values) > 10 or len(set(values)) != len(values):
            raise ValueError('App Installer fallback URIs must be distinct; maximum 10')
        if values:
            group = ET.SubElement(root, name + 'Uris')
            for value in values:
                ET.SubElement(group, name + 'Uri').text = uri(value, allow_http_loopback)
    ET.indent(root, space='  ')
    Path(output).write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n')


if __name__ == '__main__':
    create_appinstaller(output=sys.argv[2], **json.loads(Path(sys.argv[1]).read_text()))
