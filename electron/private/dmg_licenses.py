"""Declared UDIF license resources; no mounting or platform tools."""

import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import sys
import tempfile


LANGUAGES = {
    'en_US': (0, 'mac_roman'), 'fr_FR': (1, 'mac_roman'), 'en_GB': (2, 'mac_roman'),
    'de_DE': (3, 'mac_roman'), 'it_IT': (4, 'mac_roman'), 'nl_NL': (5, 'mac_roman'),
    'nl_BE': (6, 'mac_roman'), 'sv_SE': (7, 'mac_roman'), 'es_ES': (8, 'mac_roman'),
    'da_DK': (9, 'mac_roman'), 'pt_PT': (10, 'mac_roman'), 'fr_CA': (11, 'mac_roman'),
    'nb_NO': (12, 'mac_roman'), 'ja_JP': (14, 'shift_jis'), 'en_AU': (15, 'mac_roman'),
    'fi_FI': (17, 'mac_roman'), 'fr_CH': (18, 'mac_roman'), 'de_CH': (19, 'mac_roman'),
    'ru_RU': (49, 'mac_cyrillic'), 'ko_KR': (51, 'euc_kr'), 'zh_CN': (52, 'gb2312'),
    'zh_TW': (53, 'big5'), 'pt_BR': (71, 'mac_roman'), 'de_AT': (92, 'mac_roman'),
    'fr_BE': (98, 'mac_roman'), 'en_SG': (100, 'mac_roman'), 'en_IE': (108, 'mac_roman'),
}
LABELS = ('languageName', 'agree', 'disagree', 'print', 'save', 'message')


def read_limited(path, limit):
    with Path(path).open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('DMG license input exceeds size limit')
    return data


def text_rtf(data):
    text = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    if not text.strip() or any(ord(char) < 32 and char not in '\n\t' for char in text):
        raise ValueError('DMG license text is empty or contains controls')
    result = [r'{\rtf1\ansi\ansicpg1252\uc1 ']
    for char in text:
        if char == '\n':
            result.append('\\par\n')
        elif char == '\t':
            result.append(r'\tab ')
        elif char in '\\{}':
            result.append('\\' + char)
        elif ord(char) < 128:
            result.append(char)
        else:
            for (unit,) in struct.iter_unpack('<h', char.encode('utf-16le')):
                result.append('\\u' + str(unit) + '?')
    return (''.join(result) + '}').encode('ascii')


def license_resources(licenses, default_language='en_US', labels=''):
    if not 1 <= len(licenses) <= 32:
        raise ValueError('DMG licenses require 1..32 declared languages')
    locales = [entry['locale'] for entry in licenses]
    if len(set(locales)) != len(locales) or any(locale not in LANGUAGES for locale in locales):
        raise ValueError('Invalid or duplicate DMG license language')
    if default_language not in locales:
        raise ValueError('Default DMG license language must have a declared license')
    overrides = json.loads(read_limited(labels, 65536)) if labels else {}
    if not isinstance(overrides, dict) or set(overrides) - set(locales):
        raise ValueError('DMG license labels require declared languages')
    resources = {'LPic': [], 'STR#': [], 'RTF ': [], 'TEXT': []}
    mappings = []
    total = 0
    for index, entry in enumerate(sorted(licenses, key=lambda item: item['locale'])):
        locale = entry['locale']
        language, encoding = LANGUAGES[locale]
        path = Path(entry['source'])
        data = read_limited(path, 2 * 1024**2)
        total += len(data)
        if total > 16 * 1024**2:
            raise ValueError('DMG license inputs exceed total size limit')
        kind = 'RTF '
        if path.suffix == '.txt':
            body = text_rtf(data)
            try:
                plain = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r').encode(encoding)
            except UnicodeEncodeError:
                pass
            else:
                body, kind = plain, 'TEXT'
        elif path.suffix == '.rtf' and data.startswith(b'{\\rtf1') and data.rstrip().endswith(b'}'):
            body = data
        else:
            raise ValueError('DMG licenses require UTF-8 .txt or .rtf files')
        custom = overrides.get(locale, {})
        if not isinstance(custom, dict) or set(custom) - set(LABELS):
            raise ValueError('Unknown DMG license label field')
        values = dict(zip(LABELS, [locale, 'Agree', 'Disagree', 'Print', 'Save', 'Read license before continuing.']))
        values.update(custom)
        strings = []
        for field in LABELS:
            value = values[field]
            if (not isinstance(value, str) or not value.strip()
                    or any(ord(char) < 32 and not (field == 'message' and char in '\r\n\t') for char in value)):
                raise ValueError('DMG license labels require nonempty text without controls')
            encoded = value.encode(encoding)
            if len(encoded) > 255:
                raise ValueError('DMG license label exceeds 255 encoded bytes')
            strings.append(bytes([len(encoded)]) + encoded)
        identity = str(5000 + index)
        resources['STR#'].append({'Attributes': '0x0000', 'ID': identity, 'Name': locale,
                                  'Data': struct.pack('>H', 6) + b''.join(strings)})
        resources[kind].append({'Attributes': '0x0000', 'ID': identity, 'Name': locale + ' SLA', 'Data': body})
        mappings.append(struct.pack('>hhh', language, index, int(encoding in ('shift_jis', 'euc_kr', 'gb2312', 'big5'))))
    resources['LPic'].append({'Attributes': '0x0000', 'ID': '5000', 'Name': '',
                              'Data': struct.pack('>hH', LANGUAGES[default_language][0], len(mappings)) + b''.join(mappings)})
    return {kind: entries for kind, entries in resources.items() if entries}


def license_image(source, output, licenses, default_language='en_US', labels=''):
    source, output = Path(source), Path(output)
    inputs = [source, *[Path(entry['source']) for entry in licenses], *([Path(labels)] if labels else [])]
    if any(output.resolve() == path.resolve(strict=True) for path in inputs):
        raise ValueError('DMG license output must be outside its inputs')
    added = license_resources(licenses, default_language, labels)
    size = source.stat().st_size
    if not 512 <= size <= 16 * 1024**3:
        raise ValueError('DMG license image size exceeds limits')
    with source.open('rb') as content:
        content.seek(-512, 2)
        footer = bytearray(content.read(512))
        if footer[:4] != b'koly' or struct.unpack_from('>II', footer, 4) != (4, 512):
            raise ValueError('Invalid DMG license image footer')
        xml_offset, xml_size = struct.unpack_from('>QQ', footer, 216)
        data_offset, data_size, resource_offset, resource_size = struct.unpack_from('>QQQQ', footer, 24)
        if (any(struct.unpack_from('>QQ', footer, 296)) or resource_offset or resource_size
                or not 0 < xml_size <= 64 * 1024**2 or xml_offset + xml_size != size - 512
                or data_offset + data_size > xml_offset):
            raise ValueError('DMG licenses require an unsigned image with bounded XML resources')
        content.seek(xml_offset)
        metadata = plistlib.loads(content.read(xml_size))
        fork = metadata.get('resource-fork') if isinstance(metadata, dict) else None
        if not isinstance(fork, dict) or not fork.get('blkx') or set(fork) & {'LPic', 'STR#', 'TEXT', 'RTF '}:
            raise ValueError('DMG license resources conflict with existing image metadata')
        fork.update(added)
        xml = plistlib.dumps(metadata, fmt=plistlib.FMT_XML, sort_keys=True)
        if len(xml) > 64 * 1024**2:
            raise ValueError('DMG license XML exceeds size limit')
        struct.pack_into('>Q', footer, 224, len(xml))
        footer[64:80] = hashlib.sha256(footer[64:80] + xml).digest()[:16]
        with tempfile.TemporaryDirectory(prefix='electron-dmg-license-', dir=output.parent) as temporary:
            result = Path(temporary) / 'release.dmg'
            content.seek(0)
            with result.open('wb') as target:
                remaining = xml_offset
                while remaining:
                    data = content.read(min(remaining, 1024**2))
                    if not data:
                        raise ValueError('Truncated DMG license image')
                    target.write(data)
                    remaining -= len(data)
                target.write(xml)
                target.write(footer)
            result.chmod(0o644)
            os.utime(result, (0, 0))
            os.replace(result, output)


if __name__ == '__main__':
    license_image(**json.loads(Path(sys.argv[1]).read_text()), output=sys.argv[2])
