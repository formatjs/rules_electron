// SPDX-License-Identifier: MIT
#include <windows.h>
#include <shellapi.h>

#include <string>

int main() {
  int count = 0;
  wchar_t** arguments = CommandLineToArgvW(GetCommandLineW(), &count);
  if (!arguments || count < 2)
    return 1;
  if (count >= 5 && std::wstring(arguments[2]) == L"--raw-options") {
    const std::wstring command = GetCommandLineW();
    if (command.find(L" /S ") == std::wstring::npos ||
        command.find(L" --updated") == std::wstring::npos)
      return 8;
  }
  HANDLE token = nullptr;
  TOKEN_ELEVATION elevation{};
  DWORD size = 0;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
    return 2;
  const bool queried = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &size);
  CloseHandle(token);
  if (!queried || !elevation.TokenIsElevated)
    return 3;
  std::wstring payload;
  for (int index = 2; index < count; ++index) {
    payload += arguments[index];
    payload += L'\0';
  }
  HANDLE output = CreateFileW(arguments[1], GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (output == INVALID_HANDLE_VALUE)
    return 4;
  DWORD written = 0;
  const DWORD expected = static_cast<DWORD>(payload.size() * sizeof(wchar_t));
  const bool complete = WriteFile(output, payload.data(), expected, &written, nullptr) && written == expected;
  CloseHandle(output);
  if (count >= 4 && std::wstring(arguments[2]) == L"--hold") {
    DWORD waited = 0;
    while (GetFileAttributesW(arguments[3]) == INVALID_FILE_ATTRIBUTES) {
      if (waited >= 30000)
        return 6;
      Sleep(20);
      waited += 20;
    }
  }
  LocalFree(arguments);
  return complete ? 37 : 5;
}
