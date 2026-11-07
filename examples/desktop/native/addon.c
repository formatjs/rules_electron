#include <node_api.h>

NAPI_MODULE_INIT() {
  napi_value answer;
  if (napi_create_int32(env, 42, &answer) != napi_ok ||
      napi_set_named_property(env, exports, "answer", answer) != napi_ok) {
    napi_throw_error(env, NULL, "Could not initialize example addon");
    return NULL;
  }
  return exports;
}
