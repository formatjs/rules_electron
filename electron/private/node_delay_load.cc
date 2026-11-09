#include <windows.h>
#include <delayimp.h>

static FARPROC WINAPI LoadElectron(unsigned event, PDelayLoadInfo info) {
  if (event == dliNotePreLoadLibrary &&
      (!lstrcmpiA(info->szDll, "node.exe") || !lstrcmpiA(info->szDll, "node.dll"))) {
    return reinterpret_cast<FARPROC>(GetModuleHandleW(nullptr));
  }
  return nullptr;
}

extern "C" {
PfnDliHook __pfnDliNotifyHook2 = LoadElectron;
PfnDliHook __pfnDliFailureHook2 = nullptr;
}
