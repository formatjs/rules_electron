#include <node.h>
#include <memory>

static void BackingStore(const v8::FunctionCallbackInfo<v8::Value>& args) {
  auto* isolate = args.GetIsolate();
  std::shared_ptr<v8::BackingStore> shared =
      v8::ArrayBuffer::NewBackingStore(isolate, 4);
  auto buffer = v8::ArrayBuffer::New(isolate, shared);
  auto roundtrip = buffer->GetBackingStore();
  if (roundtrip.get() != shared.get() || roundtrip.use_count() < 2) {
    isolate->ThrowException(v8::Exception::Error(
        v8::String::NewFromUtf8Literal(isolate, "Backing store ownership failed")));
    return;
  }
  auto* bytes = static_cast<unsigned char*>(roundtrip->Data());
  bytes[0] = 0x12;
  bytes[1] = 0x34;
  bytes[2] = 0x56;
  bytes[3] = 0x78;
  args.GetReturnValue().Set(buffer);
}

static void Answer(const v8::FunctionCallbackInfo<v8::Value>& args) {
  args.GetReturnValue().Set(v8::Integer::New(args.GetIsolate(), 42));
}

NODE_MODULE_INIT() {
  v8::Isolate* isolate = v8::Isolate::GetCurrent();
  exports->Set(context, v8::String::NewFromUtf8Literal(isolate, "answer"),
               v8::Function::New(context, Answer).ToLocalChecked()).Check();
  exports->Set(context, v8::String::NewFromUtf8Literal(isolate, "backingStore"),
               v8::Function::New(context, BackingStore).ToLocalChecked()).Check();
  exports->Set(context, v8::String::NewFromUtf8Literal(isolate, "moduleAbi"),
               v8::Integer::New(isolate, NODE_MODULE_VERSION)).Check();
}
