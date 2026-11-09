#include <windows.h>
#include <appxpackaging.h>
#include <shlwapi.h>
#include <wrl/client.h>
#include <wintrust.h>
#include <softpub.h>

#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <vector>

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

int wmain(int argc, wchar_t** argv) {
  if (argc == 4 && std::wcscmp(argv[1], L"--signature") == 0) {
    validate_signature(argv[2], argv[3]);
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
