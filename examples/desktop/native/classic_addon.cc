#include <node.h>

static void Answer(const v8::FunctionCallbackInfo<v8::Value>& args) {
  args.GetReturnValue().Set(v8::Integer::New(args.GetIsolate(), 42));
}

NODE_MODULE_INIT() {
  v8::Isolate* isolate = v8::Isolate::GetCurrent();
  exports->Set(context, v8::String::NewFromUtf8Literal(isolate, "answer"),
               v8::Function::New(context, Answer).ToLocalChecked()).Check();
  exports->Set(context, v8::String::NewFromUtf8Literal(isolate, "moduleAbi"),
               v8::Integer::New(isolate, NODE_MODULE_VERSION)).Check();
}
