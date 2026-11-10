#include <windows.h>
#include <appxpackaging.h>
#include <shlwapi.h>
#include <shobjidl.h>
#include <shlguid.h>
#include <wrl/client.h>
#include <wintrust.h>
#include <softpub.h>

#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <string>
#include <vector>
#include <algorithm>
#include <cstring>
#include <set>

using Microsoft::WRL::ComPtr;

static void check(HRESULT result, const char* step) {
  if (FAILED(result)) {
    std::fprintf(stderr, "MSIX_API_FAILURE %s 0x%08lx\n", step,
                 static_cast<unsigned long>(result));
    std::exit(1);
  }
}

static void require(bool condition, const char* step) {
  if (!condition) {
    std::fprintf(stderr, "MSIX_ASSERT_FAILURE %s\n", step);
    std::exit(1);
  }
}

static void validate_signature(const wchar_t* path, const wchar_t* expected) {
  WINTRUST_FILE_INFO file{};
  file.cbStruct = sizeof(file);
  file.pcwszFilePath = path;
  WINTRUST_DATA trust{};
  trust.cbStruct = sizeof(trust);
  trust.dwUIChoice = WTD_UI_NONE;
  trust.fdwRevocationChecks = WTD_REVOKE_NONE;
  trust.dwUnionChoice = WTD_CHOICE_FILE;
  trust.pFile = &file;
  trust.dwStateAction = WTD_STATEACTION_VERIFY;
  trust.dwProvFlags = WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL;
  GUID action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
  const LONG result = WinVerifyTrust(nullptr, &action, &trust);
  trust.dwStateAction = WTD_STATEACTION_CLOSE;
  WinVerifyTrust(nullptr, &action, &trust);
  std::printf("MSIX_TRUST_RESULT 0x%08lx\n", static_cast<unsigned long>(result));
  bool matches = false;
  if (std::wcscmp(expected, L"unsigned") == 0)
    matches = result == TRUST_E_NOSIGNATURE;
  else if (std::wcscmp(expected, L"untrusted") == 0)
    matches = result == CERT_E_UNTRUSTEDROOT;
  else if (std::wcscmp(expected, L"valid") == 0)
    matches = result == ERROR_SUCCESS;
  else if (std::wcscmp(expected, L"tampered") == 0)
    matches = result == TRUST_E_BAD_DIGEST;
  require(matches, "signature_trust_result");
}

static bool has_handler(const wchar_t* name, bool protocol,
                        const std::wstring& application, IAssocHandler** selected = nullptr) {
  ComPtr<IEnumAssocHandlers> handlers;
  HRESULT result = protocol
      ? SHAssocEnumHandlersForProtocolByApplication(name, IID_PPV_ARGS(&handlers))
      : SHAssocEnumHandlers(name, ASSOC_FILTER_NONE, &handlers);
  if (result == S_FALSE || result == HRESULT_FROM_WIN32(ERROR_NO_ASSOCIATION))
    return false;
  check(result, "handler_enumeration");
  require(handlers.Get() != nullptr, "handler_enumeration_result");
  for (unsigned index = 0; index < 4096; ++index) {
    ComPtr<IAssocHandler> handler;
    ULONG fetched = 0;
    result = handlers->Next(1, &handler, &fetched);
    if (result == S_FALSE)
      return false;
    check(result, "next_handler");
    require(fetched == 1 && handler.Get() != nullptr, "next_handler_result");
    ComPtr<IObjectWithAppUserModelID> identity;
    if (FAILED(handler.As(&identity)))
      continue;
    LPWSTR identifier = nullptr;
    result = identity->GetAppID(&identifier);
    const bool matches = SUCCEEDED(result) && identifier && application == identifier;
    CoTaskMemFree(identifier);
    if (matches) {
      if (selected) check(handler.CopyTo(selected), "selected_handler");
      return true;
    }
  }
  require(false, "handler_enumeration_limit");
  return false;
}

static void validate_handlers(const wchar_t* family, const wchar_t* state) {
  const bool present = std::wcscmp(state, L"present") == 0;
  require(present || std::wcscmp(state, L"absent") == 0, "handler_state");
  check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED), "handler_com_initialize");
  const std::wstring application = std::wstring(family) + L"!App";
  for (const wchar_t* scheme : {L"sample-msix", L"sample-msix-alt"})
    require(has_handler(scheme, true, application) == present, "protocol_handler_state");
  for (const wchar_t* extension : {L".samplemsix", L".samplemsix_alt"})
    require(has_handler(extension, false, application) == present, "file_handler_state");
  CoUninitialize();
  std::puts(present ? "MSIX_HANDLERS_PRESENT" : "MSIX_HANDLERS_REMOVED");
}

static void activate(const wchar_t* family, const wchar_t* kind,
                     const wchar_t* value) {
  const bool protocol = std::wcscmp(kind, L"protocol") == 0;
  require(protocol || std::wcscmp(kind, L"file") == 0, "activation_kind");
  check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED), "activation_com_initialize");
  ComPtr<IShellItem> item;
  check(SHCreateItemFromParsingName(value, nullptr, IID_PPV_ARGS(&item)),
        "activation_shell_item");
  ComPtr<IShellItemArray> items;
  check(SHCreateShellItemArrayFromShellItem(item.Get(), IID_PPV_ARGS(&items)),
        "activation_shell_array");
  const std::wstring application = std::wstring(family) + L"!App";
  const std::wstring name = protocol ? std::wstring(value).substr(0, std::wstring(value).find(L':'))
                                    : PathFindExtensionW(value);
  ComPtr<IAssocHandler> handler;
  require(has_handler(name.c_str(), protocol, application, &handler), "activation_registered_handler");
  ComPtr<IDataObject> data;
  check(items->BindToHandler(nullptr, BHID_DataObject, IID_PPV_ARGS(&data)),
        "activation_data_object");
  check(handler->Invoke(data.Get()), "activation_handler_invoke");
  std::puts("MSIX_REGISTERED_HANDLER_INVOKED");
}

static void validate(IAppxFile* file, IAppxBlockMapReader* blockmap,
                     bool* tamper_checked, unsigned* count) {
  LPWSTR name = nullptr;
  check(file->GetName(&name), "file_name");
  ComPtr<IAppxBlockMapFile> blocks;
  check(blockmap->GetFile(name, &blocks), "blockmap_file");
  const bool large = std::wcscmp(name, L"payloads\\\u4e16\u754c.bin") == 0;
  CoTaskMemFree(name);
  ComPtr<IStream> stream;
  check(file->GetStream(&stream), "payload_stream");
  BOOL valid = FALSE;
  check(blocks->ValidateFileHash(stream.Get(), &valid), "payload_hash");
  require(valid != FALSE, "payload_hash");
  ++*count;
  if (large) {
    UINT64 size = 0;
    check(file->GetSize(&size), "payload_size");
    require(size == 262148, "multiblock_size");
    check(stream->Seek({}, STREAM_SEEK_SET, nullptr), "payload_rewind");
    std::vector<unsigned char> bytes(static_cast<size_t>(size));
    ULONG read = 0;
    check(stream->Read(bytes.data(), static_cast<ULONG>(size), &read), "payload_read");
    require(read == size, "payload_read_length");
    bytes[65536] ^= 1;
    ComPtr<IStream> changed;
    check(CreateStreamOnHGlobal(nullptr, TRUE, &changed), "tamper_stream");
    ULONG written = 0;
    check(changed->Write(bytes.data(), read, &written), "tamper_write");
    require(written == read, "tamper_write_length");
    check(changed->Seek({}, STREAM_SEEK_SET, nullptr), "tamper_rewind");
    valid = TRUE;
    const HRESULT result = blocks->ValidateFileHash(changed.Get(), &valid);
    require(SUCCEEDED(result) && valid == FALSE, "tamper_rejected");
    *tamper_checked = true;
  }
}

static void validate_bundle(const wchar_t* path, const wchar_t* expected_version) {
  unsigned a, b, c, d;
  require(std::swscanf(expected_version, L"%u.%u.%u.%u", &a, &b, &c, &d) == 4 &&
              a <= 65535 && b <= 65535 && c <= 65535 && d <= 65535,
          "bundle_expected_version");
  const UINT64 expected = (UINT64{a} << 48) | (UINT64{b} << 32) | (UINT64{c} << 16) | d;
  check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "bundle_com_initialize");
  ComPtr<IStream> stream;
  check(SHCreateStreamOnFileEx(path, STGM_READ | STGM_SHARE_DENY_WRITE, 0, FALSE, nullptr, &stream), "bundle_stream");
  ComPtr<IAppxBundleFactory> factory;
  check(CoCreateInstance(__uuidof(AppxBundleFactory), nullptr, CLSCTX_INPROC_SERVER,
                         IID_PPV_ARGS(&factory)), "bundle_factory");
  ComPtr<IAppxBundleReader> reader;
  check(factory->CreateBundleReader(stream.Get(), &reader), "bundle_reader");
  ComPtr<IAppxBundleManifestReader> manifest;
  check(reader->GetManifest(&manifest), "bundle_manifest");
  ComPtr<IAppxManifestPackageId> identity;
  check(manifest->GetPackageId(&identity), "bundle_identity");
  UINT64 version;
  check(identity->GetVersion(&version), "bundle_version");
  require(version == expected, "bundle_version_matches");
  ComPtr<IAppxFactory> package_factory;
  check(CoCreateInstance(__uuidof(AppxFactory), nullptr, CLSCTX_INPROC_SERVER,
                         IID_PPV_ARGS(&package_factory)), "bundle_package_factory");
  ComPtr<IAppxBundleManifestPackageInfoEnumerator> packages;
  check(manifest->GetPackageInfoItems(&packages), "bundle_package_items");
  BOOL current = FALSE;
  check(packages->GetHasCurrent(&current), "bundle_enumeration");
  std::set<APPX_PACKAGE_ARCHITECTURE> architectures;
  while (current) {
    ComPtr<IAppxBundleManifestPackageInfo> info;
    check(packages->GetCurrent(&info), "bundle_package_info");
    ComPtr<IAppxManifestPackageId> package_id;
    check(info->GetPackageId(&package_id), "bundle_package_identity");
    APPX_PACKAGE_ARCHITECTURE architecture;
    check(package_id->GetArchitecture(&architecture), "bundle_package_architecture");
    require(architectures.insert(architecture).second, "bundle_unique_architecture");
    check(package_id->GetVersion(&version), "bundle_package_version");
    require(version == expected, "bundle_package_version_matches");
    LPWSTR name = nullptr;
    check(info->GetFileName(&name), "bundle_package_name");
    ComPtr<IAppxFile> file;
    check(reader->GetPayloadPackage(name, &file), "bundle_package_file");
    CoTaskMemFree(name);
    APPX_COMPRESSION_OPTION compression;
    check(file->GetCompressionOption(&compression), "bundle_compression");
    require(compression == APPX_COMPRESSION_OPTION_NONE, "bundle_payload_stored");
    UINT64 offset, size, actual_size;
    check(info->GetOffset(&offset), "bundle_offset");
    check(info->GetSize(&size), "bundle_size");
    check(file->GetSize(&actual_size), "bundle_actual_size");
    require(size == actual_size && offset != 0, "bundle_embedded_size");
    ComPtr<IStream> payload;
    check(file->GetStream(&payload), "bundle_payload_stream");
    const ULONG length = static_cast<ULONG>(std::min<UINT64>(size, 65536));
    std::vector<unsigned char> nested(length), raw(length);
    ULONG read;
    check(payload->Read(nested.data(), length, &read), "bundle_payload_read");
    require(read == length, "bundle_payload_length");
    LARGE_INTEGER position;
    position.QuadPart = static_cast<LONGLONG>(offset);
    check(stream->Seek(position, STREAM_SEEK_SET, nullptr), "bundle_offset_seek");
    check(stream->Read(raw.data(), length, &read), "bundle_offset_read");
    require(read == length && raw == nested, "bundle_offset_bytes_match");
    check(payload->Seek({}, STREAM_SEEK_SET, nullptr), "bundle_payload_rewind");
    ComPtr<IAppxPackageReader> package;
    check(package_factory->CreatePackageReader(payload.Get(), &package), "bundle_inner_reader");
    ComPtr<IAppxManifestReader> inner_manifest;
    check(package->GetManifest(&inner_manifest), "bundle_inner_manifest");
    ComPtr<IAppxManifestPackageId> inner_id;
    check(inner_manifest->GetPackageId(&inner_id), "bundle_inner_identity");
    APPX_PACKAGE_ARCHITECTURE inner_architecture;
    check(inner_id->GetArchitecture(&inner_architecture), "bundle_inner_architecture");
    require(inner_architecture == architecture, "bundle_inner_architecture_matches");
    check(packages->MoveNext(&current), "bundle_enumeration_next");
  }
  require(architectures == std::set<APPX_PACKAGE_ARCHITECTURE>{APPX_PACKAGE_ARCHITECTURE_X64, APPX_PACKAGE_ARCHITECTURE_ARM64},
          "bundle_both_native_cpus");
  ComPtr<IAppxBlockMapReader> blockmap;
  check(reader->GetBlockMap(&blockmap), "bundle_blockmap");
  ComPtr<IAppxBlockMapFilesEnumerator> entries;
  check(blockmap->GetFiles(&entries), "bundle_blockmap_files");
  check(entries->GetHasCurrent(&current), "bundle_blockmap_start");
  require(current, "bundle_manifest_in_blockmap");
  check(entries->MoveNext(&current), "bundle_blockmap_next");
  require(!current, "bundle_only_manifest_hashed");
  ComPtr<IAppxBlockMapFile> blocks;
  check(blockmap->GetFile(L"AppxMetadata\\AppxBundleManifest.xml", &blocks), "bundle_manifest_blocks");
  ComPtr<IAppxFile> footprint;
  check(reader->GetFootprintFile(APPX_BUNDLE_FOOTPRINT_FILE_TYPE_MANIFEST, &footprint), "bundle_manifest_file");
  ComPtr<IStream> manifest_stream;
  check(footprint->GetStream(&manifest_stream), "bundle_manifest_stream");
  BOOL valid = FALSE;
  check(blocks->ValidateFileHash(manifest_stream.Get(), &valid), "bundle_manifest_hash");
  require(valid, "bundle_manifest_hash_matches");
  std::puts("MSIX_BUNDLE_PACKAGING_API_OK");
}

int wmain(int argc, wchar_t** argv) {
  if (argc == 4 && std::wcscmp(argv[1], L"--bundle") == 0) {
    validate_bundle(argv[2], argv[3]);
    return 0;
  }
  if (argc == 5 && std::wcscmp(argv[1], L"--activate") == 0) {
    activate(argv[2], argv[3], argv[4]);
    return 0;
  }
  if (argc == 4 && std::wcscmp(argv[1], L"--signature") == 0) {
    validate_signature(argv[2], argv[3]);
    return 0;
  }
  if (argc == 4 && std::wcscmp(argv[1], L"--handlers") == 0) {
    validate_handlers(argv[2], argv[3]);
    return 0;
  }
  require(argc == 2, "arguments");
  check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "com_initialize");
  ComPtr<IAppxFactory> factory;
  check(CoCreateInstance(__uuidof(AppxFactory), nullptr, CLSCTX_INPROC_SERVER,
                         IID_PPV_ARGS(&factory)), "factory");
  ComPtr<IStream> stream;
  check(SHCreateStreamOnFileEx(argv[1], STGM_READ | STGM_SHARE_DENY_WRITE, 0,
                              FALSE, nullptr, &stream), "package_stream");
  ComPtr<IAppxPackageReader> reader;
  check(factory->CreatePackageReader(stream.Get(), &reader), "package_reader");
  ComPtr<IAppxManifestReader> manifest;
  check(reader->GetManifest(&manifest), "manifest");
  ComPtr<IAppxManifestPackageId> identity;
  check(manifest->GetPackageId(&identity), "identity");
  APPX_PACKAGE_ARCHITECTURE architecture;
  check(identity->GetArchitecture(&architecture), "architecture");
#if defined(_M_ARM64)
  require(architecture == APPX_PACKAGE_ARCHITECTURE_ARM64, "matching_arm64");
#else
  require(architecture == APPX_PACKAGE_ARCHITECTURE_X64, "matching_x64");
#endif
  UINT64 version = 0;
  check(identity->GetVersion(&version), "version");
  require(version == ((UINT64{1} << 48) | 7), "explicit_version");
  ComPtr<IAppxBlockMapReader> blockmap;
  check(reader->GetBlockMap(&blockmap), "blockmap");
  ComPtr<IAppxFilesEnumerator> files;
  check(reader->GetPayloadFiles(&files), "payload_files");
  BOOL current = FALSE;
  check(files->GetHasCurrent(&current), "enumeration_start");
  bool tamper_checked = false;
  unsigned count = 0;
  while (current) {
    ComPtr<IAppxFile> file;
    check(files->GetCurrent(&file), "enumeration_current");
    validate(file.Get(), blockmap.Get(), &tamper_checked, &count);
    check(files->MoveNext(&current), "enumeration_next");
  }
  require(count == 6 && tamper_checked, "all_payloads_checked");
  ComPtr<IAppxFile> manifest_file;
  check(reader->GetFootprintFile(APPX_FOOTPRINT_FILE_TYPE_MANIFEST, &manifest_file),
        "manifest_footprint");
  validate(manifest_file.Get(), blockmap.Get(), &tamper_checked, &count);
  std::puts("MSIX_PACKAGING_API_OK");
  std::puts("MSIX_BLOCK_HASH_TAMPER_REJECTED");
  return 0;
}
