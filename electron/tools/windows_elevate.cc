// SPDX-License-Identifier: MIT
#include <windows.h>
#include <shellapi.h>
#include <objbase.h>

#include <string>
#include <string_view>

namespace {

std::wstring Quote(std::wstring_view argument) {
  std::wstring result = L"\"";
  size_t slashes = 0;
  for (wchar_t character : argument) {
    if (character == L'\\') {
      ++slashes;
      continue;
    }
    result.append(slashes * (character == L'"' ? 2 : 1), L'\\');
    if (character == L'"')
      result += L'\\';
    result += character;
    slashes = 0;
  }
  result.append(slashes * 2, L'\\');
  result += L'"';
  return result;
}

DWORD Elevate(int count, wchar_t** arguments) {
  if (count < 2)
    return ERROR_INVALID_PARAMETER;
  const std::wstring executable = arguments[1];
  const bool absolute = executable.compare(0, 2, L"\\\\") == 0 ||
      (executable.size() >= 3 && executable[1] == L':' &&
       (executable[2] == L'\\' || executable[2] == L'/'));
  if (!absolute)
    return ERROR_BAD_PATHNAME;
  const DWORD attributes = GetFileAttributesW(executable.c_str());
  if (attributes == INVALID_FILE_ATTRIBUTES)
    return GetLastError();
  if (attributes & FILE_ATTRIBUTE_DIRECTORY)
    return ERROR_ACCESS_DENIED;
  DWORD binary_type = 0;
  if (!GetBinaryTypeW(executable.c_str(), &binary_type))
    return GetLastError();
  std::wstring parameters;
  for (int index = 2; index < count; ++index) {
    if (!parameters.empty())
      parameters += L' ';
    parameters += Quote(arguments[index]);
  }
  const auto separator = executable.find_last_of(L"\\/");
  const std::wstring directory = executable.substr(0, separator + 1);
  SHELLEXECUTEINFOW operation{};
  operation.cbSize = sizeof(operation);
  operation.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
  operation.lpVerb = L"runas";
  operation.lpFile = executable.c_str();
  operation.lpParameters = parameters.c_str();
  operation.lpDirectory = directory.c_str();
  operation.nShow = SW_SHOWNORMAL;
  if (!ShellExecuteExW(&operation))
    return GetLastError();
  if (!operation.hProcess)
    return ERROR_INVALID_HANDLE;
  DWORD exit_code = ERROR_GEN_FAILURE;
  if (WaitForSingleObject(operation.hProcess, INFINITE) != WAIT_OBJECT_0 ||
      !GetExitCodeProcess(operation.hProcess, &exit_code))
    exit_code = GetLastError();
  CloseHandle(operation.hProcess);
  return exit_code;
}

}  // namespace

int main() {
  int count = 0;
  wchar_t** arguments = CommandLineToArgvW(GetCommandLineW(), &count);
  if (!arguments)
    return static_cast<int>(GetLastError());
  const HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
  const DWORD result = SUCCEEDED(initialized) ? Elevate(count, arguments) : ERROR_INVALID_FUNCTION;
  LocalFree(arguments);
  if (SUCCEEDED(initialized))
    CoUninitialize();
  return static_cast<int>(result);
}
