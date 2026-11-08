#include <node_api.h>
#ifdef _WIN32
#include <windows.h>
#endif

typedef napi_status(NAPI_CDECL *create_int32_type)(napi_env, int32_t, napi_value*);
typedef napi_status(NAPI_CDECL *set_property_type)(napi_env, napi_value, const char*, napi_value);
typedef napi_status(NAPI_CDECL *throw_error_type)(napi_env, const char*, const char*);

NAPI_MODULE_INIT() {
  // Resolve the renamed host process, avoiding a hard-coded node.exe import.
#ifdef _WIN32
  HMODULE host = GetModuleHandleW(NULL);
  create_int32_type create_int32 = (create_int32_type)GetProcAddress(host, "napi_create_int32");
  set_property_type set_property = (set_property_type)GetProcAddress(host, "napi_set_named_property");
  throw_error_type throw_error = (throw_error_type)GetProcAddress(host, "napi_throw_error");
  if (!create_int32 || !set_property || !throw_error) return NULL;
#else
  create_int32_type create_int32 = napi_create_int32;
  set_property_type set_property = napi_set_named_property;
  throw_error_type throw_error = napi_throw_error;
#endif
  napi_value answer;
  if (create_int32(env, 42, &answer) != napi_ok ||
      set_property(env, exports, "answer", answer) != napi_ok) {
    throw_error(env, NULL, "Could not initialize example addon");
    return NULL;
  }
#ifdef _WIN32
  typedef HRESULT(WINAPI *get_app_id_type)(PWSTR*);
  typedef void(WINAPI *free_memory_type)(LPVOID);
  typedef napi_status(NAPI_CDECL *create_string_type)(napi_env, const char16_t*, size_t, napi_value*);
  get_app_id_type get_app_id = (get_app_id_type)GetProcAddress(GetModuleHandleW(L"shell32.dll"), "GetCurrentProcessExplicitAppUserModelID");
  free_memory_type free_memory = (free_memory_type)GetProcAddress(GetModuleHandleW(L"ole32.dll"), "CoTaskMemFree");
  create_string_type create_string = (create_string_type)GetProcAddress(host, "napi_create_string_utf16");
  PWSTR identifier = NULL;
  if (!get_app_id || !free_memory || !create_string || FAILED(get_app_id(&identifier))) {
    throw_error(env, NULL, "Could not read process AppUserModelID");
    return NULL;
  }
  napi_value app_id;
  napi_status status = create_string(env, (const char16_t*)identifier, NAPI_AUTO_LENGTH, &app_id);
  free_memory(identifier);
  if (status != napi_ok || set_property(env, exports, "appUserModelId", app_id) != napi_ok) {
    throw_error(env, NULL, "Could not expose process AppUserModelID");
    return NULL;
  }
#endif
  return exports;
}
