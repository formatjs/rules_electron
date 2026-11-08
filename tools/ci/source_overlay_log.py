"""Classify exact Electron source CI failures without forwarding raw logs."""

import json
import base64
import hashlib
import os
import posixpath
import re
import urllib.request
import urllib.parse
from pathlib import Path

from buildbuddy_artifacts import NoRedirect, api_request, invocation_id
from buildbuddy_log import read_log, resource_diagnostics
from profile_summary import decode_profile, summarize_source


def source_profile_diagnostics(invocation, key):
    if not invocation.get("success") or invocation.get("invocationStatus") != "COMPLETE_INVOCATION_STATUS":
        return
    for name in ["source-graphics-profile.json.gz", "source-components-profile.json.gz", "source-tests-profile.json.gz", "source-consumer-profile.json.gz"]:
        matches = [artifact for artifact in invocation.get("artifacts", []) if artifact.get("name", "").rsplit("/", 1)[-1] == name]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("Expected one source phase profile")
        uri = matches[0].get("uri", "")
        parsed = urllib.parse.urlsplit(uri)
        digest = re.search(r"/blobs/([0-9a-f]{64})/(\d+)$", parsed.path)
        if parsed.scheme != "bytestream" or parsed.netloc not in ("formatjs.buildbuddy.io", "remote.buildbuddy.io") or not digest or int(digest[2]) > 64 * 1024**2:
            raise ValueError("Invalid source profile artifact store or size")
        with api_request("GetFile", {"uri": uri}, key) as response:
            data = response.read(int(digest[2]) + 1)
        if len(data) != int(digest[2]) or hashlib.sha256(data).hexdigest() != digest[1]:
            raise ValueError("Source profile digest mismatch")
        print("Verified source profile " + name + ":", json.dumps(summarize_source(decode_profile(data)), sort_keys=True))


def classify(log):
    patterns = {
        "UNKNOWN_OPTION": r"Unrecognized option|unrecognized flag|bad option",
        "TOOLCHAIN_RESOLUTION": r"No matching toolchains|Unable to find an execution platform",
        "IMAGE_PULL": r"failed to pull|pull access denied|manifest unknown",
        "AUTHORIZATION": r"Unauthenticated|PermissionDenied|unauthorized",
        "EXECUTOR_UNAVAILABLE": r"No registered executors|No execution nodes",
        "NETWORK_POLICY_UNENFORCED": r"Build action unexpectedly completed an external TLS exchange",
        "NETWORK_UNREACHABLE": r"Network is unreachable|Temporary failure in name resolution|Could not resolve host",
        "SOURCE_FETCH": r"Error downloading|download failed",
        "MISSING_BUILD_FILE": r"BUILD file not found",
        "MISSING_PACKAGE": r"no such package",
        "MISSING_TARGET": r"no such target|not declared in package",
        "NO_TEST_TARGETS": r"No test targets were found|No tests found",
        "INCOMPATIBLE_TARGET": r"incompatible and cannot|target.*incompatible",
        "STRATEGY_CONFIGURATION": r"No usable strategy|strategy.*not supported|strategy.*not found|invalid strategy|No default strategy",
        "TEST_STRATEGY": r"test strategy|TestRunner",
        "BAZEL_BUSY": r"Another command.*running|Waiting for server process|waiting for.*lock|Waiting for.*command",
        "BAZEL_ANALYSIS": r"Analyzing:|Loading:|Computing main repo mapping",
        "BAZEL_FETCH": r"Fetching repository|fetching.*repository|Downloading.*bytes|Extracting",
        "REMOTE_CACHE_CHECK": r"checking cached actions|remote cache hit|remote cache.*check",
        "ANALYSIS_FAILED": r"Analysis of target.*failed|analysis failed|loading failed",
        "FATAL_ERROR": r"FATAL|ERROR",
        "MODULE_RESOLUTION": r"Error computing the main repository mapping",
        "BUILD_FAILED": r"Build did NOT complete successfully",
        "TEST_FAILED": r"\bFAILED\b",
        "CPP_MISSING_HEADER": r"fatal error: .*file not found",
        "CPP_TYPE_ERROR": r"no matching function|no matching member function|no matching constructor|cannot initialize|cannot convert|invalid operands",
        "CPP_STATIC_ASSERT": r"static assertion failed",
        "CPP_CONSTEXPR": r"not a constant expression|constexpr.*never produces",
        "CPP_REDEFINITION": r"redefinition of|duplicate definition|already defined",
        "CPP_TEMPLATE_DEPTH": r"recursive template instantiation|template instantiation depth|bracket nesting level exceeded",
        "CPP_TARGET_FEATURE": r"requires target feature|target specific option mismatch",
        "CPP_TEMPLATE_ARGUMENT": r"template argument|no template named|not a template|parameter pack",
        "CPP_ACCESS_CONTROL": r"is a private member|is protected within",
        "CPP_TOKEN_ERROR": r"unknown type name|extraneous|error: expected",
        "CPP_AMBIGUOUS": r"error:.*ambiguous",
        "CPP_INCOMPLETE_TYPE": r"error:.*incomplete type",
        "CPP_UNDECLARED_IDENTIFIER": r"undeclared identifier|no member named",
        "LINKER_MISSING_LIBRARY": r"unable to find library|cannot find -l|could not find library",
        "LINKER_OUTPUT_EXTENSION": r"file extension|filename extension|output extension",
        "LLVM_ATOMIC_LIBRARY": r"(?:cannot find|not found|missing|unsupported|does not exist)[^\r\n]{0,100}atomic|atomic[^\r\n]{0,100}(?:not found|missing|unsupported|does not exist)",
        "LINKER_UNDEFINED_SYMBOL": r"undefined symbol|undefined reference",
        "NODE_JS_EXCEPTION": r"\b(?:ReferenceError|TypeError|SyntaxError|RangeError|Error):",
        "EMBEDDER_RUNTIME_TEST": r"check failed: embedder",
        "IPCZ_RUNTIME_TEST": r"check failed: ipcz",
        "NETWORK_RUNTIME_TEST": r"check failed: network",
        "MOJO_RUNTIME_TEST": r"check failed: mojo",
        "FONTS_RUNTIME_TEST": r"check failed: fonts",
        "CODECS_RUNTIME_TEST": r"check failed: codecs",
        "SKIA_RUNTIME_TEST": r"check failed: skia",
        "GFX_RUNTIME_TEST": r"check failed: gfx",
        "DISPLAY_RUNTIME_TEST": r"check failed: display",
        "EVENTS_RUNTIME_TEST": r"check failed: events",
        "UI_RUNTIME_TEST": r"check failed: ui ",
        "WEBUI_RUNTIME_TEST": r"check failed: ui_webui ",
        "MEDIA_RUNTIME_TEST": r"check failed: media_runtime ",
        "BLINK_PLATFORM_TEST": r"check failed: blink_platform ",
        "BLINK_CORE_TEST": r"check failed: blink_core ",
        "BLINK_BINDINGS_TEST": r"check failed: blink_bindings ",
        "CRABBY_DECODE_TEST": r"check failed: crabby_decode ",
        "BLINK_FONT_TEST": r"check failed: blink_font ",
        "BLINK_CRASH_TEST": r"check failed: blink_crash ",
        "COMPOSITOR_TEST": r"check failed: compositor ",
        "ASOUND_ABI_TEST": r"check failed: asound_abi ",
        "NASM_ERROR": r"(?:nasm:.*(?:error|fatal)|\.asm:[0-9]+: (?:error|fatal))",
        "SYMPHONIA_RUNTIME_TEST": r"check failed: symphonia ",
        "GPU_TRANSPORT_RUNTIME_TEST": r"check failed: gpu_transport ",
        "PLATFORM_GRAPHICS_RUNTIME_TEST": r"check failed: platform_graphics ",
        "TYPESCRIPT_COMPILATION": r"error TS[0-9]{4,5}:",
        "NODE_MODULE_RESOLUTION": r"Cannot find module|Cannot find package|ERR_MODULE_NOT_FOUND|Could not resolve entry module",
        "GRIT_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes: tools/grit/grit.py",
        "GRIT_IDS_REPRODUCIBILITY": r"Generator output differs[^\r\n]*; [^\r\n]*gen/tools/gritsettings/default_resource_ids(?:,|$)",
        "GRIT_INFO_REPRODUCIBILITY": r"Generator output differs[^\r\n]*; [^\r\n]*gen/net/net_resources\.pak\.info(?:,|$)",
        "GRIT_PAK_REPRODUCIBILITY": r"Generator output differs[^\r\n]*; [^\r\n]*gen/net/net_resources\.pak(?:,|$)",
        "GRIT_HEADER_REPRODUCIBILITY": r"Generator output differs[^\r\n]*; [^\r\n]*gen/net/grit/net_resources\.h(?:,|$)",
        "GRIT_STAMP_REPRODUCIBILITY": r"Generator output differs[^\r\n]*; [^\r\n]*gen/net/net_resources_grit\.d\.stamp(?:,|$)",
        "VERSION_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes: build/util/version.py",
        "SQL_GENERATOR_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes: tools/metrics/histograms/",
        "PROTOBUF_GENERATOR_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes: tools/protoc_wrapper/",
        "NATIVE_GENERATOR_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes: build/gn_run_binary.py",
        "NSS_INTEGRITY_GENERATION": r"NSS integrity generation failed",
        "NSS_INTEGRITY_REPRODUCIBILITY": r"NSS integrity output differs across paths and mtimes",
        "NSS_INTEGRITY_IMPORT": r"No module named ['\"]nss_integrity['\"]",
        "NSS_NONCE_VECTOR": r"FAIL: test_rfc6979_appendix_a_2_2",
        "LIBNODE_RUNTIME_TEST": r"check failed: patched libnode",
        "LIBNODE_ASSERTION": r"AssertionError|ERR_ASSERTION",
        "LIBNODE_MODULE_MISSING": r"Cannot find module|ERR_UNKNOWN_BUILTIN_MODULE",
        "LIBNODE_BINDING_MISSING": r"No such binding|ERR_UNKNOWN_BUILTIN_MODULE",
        "NODE_HKDF_VECTOR": r"check failed: Node crypto HKDF vector",
        "NODE_HKDF_LENGTH": r"check failed: HKDF length boundary|check failed: oversized HKDF rejected",
        "NODE_BYTE_SWAP": r"check failed: unaligned byte swap|check failed: invalid byte count|check failed: byte swap bounds",
        "ELF_FIXTURE": r"check failed: ELF note retained",
        "POSTJECT_RESOURCE": r"check failed: embedded ELF resource bytes|check failed: missing embedded resource|check failed: ELF resource name override",
        "POSTJECT_FUSE": r"check failed: default Postject fuse",
        "TORQUE_INTERFACE_TEST": r"FAIL: test_complete_engine_interfaces_and_reproducibility",
        "TORQUE_INVALID_INPUT_TEST": r"FAIL: test_malformed_torque_(?:fails_cleanly|reports_parse_error)",
        "TORQUE_REPRODUCIBILITY": r"Torque output differs across paths and input mtimes",
        "TORQUE_ARRAY_INTERFACE": r"Regex didn't match:.*JSArray",
        "TORQUE_INTL_INTERFACE": r"Regex didn't match:.*JSCollator",
        "TORQUE_TEMPORAL_INTERFACE": r"Regex didn't match:.*JSTemporalPlainDate",
        "TORQUE_TEST_EXCEPTION": r"ERROR: test_complete_engine_interfaces_and_reproducibility|ERROR: test_malformed_torque_(?:fails_cleanly|reports_parse_error)",
        "BYTECODE_HANDLER_CONTRACT": r"check failed: bytecode handler (?:unique|name|coverage|counts)",
        "BYTECODE_WIDE_DISPATCH": r"check failed: bytecode (?:illegal wide encoding|dense index bounds|wide dispatch mapping)",
        "BYTECODE_REPRODUCIBILITY": r"check failed: bytecode generation path reproducibility",
        "BYTECODE_INPUT_FILES": r"check failed: bytecode generated file (?:readable|arguments)",
        "ICU_DATA_CONTRACT": r"check failed: ICU (?:declared data|ambient file access disabled|corrupt data rejected|pinned version)",
        "ICU_UNICODE_CONTRACT": r"check failed: ICU (?:normalization data|NFC composition|case fold preflight|Unicode case fold)",
        "ICU_LOCALE_CONTRACT": r"check failed: ICU (?:collation data|primary collation|tertiary collation|number locale data|French number formatting|word break data|Chromium word boundaries)",
        "REGEXP_TABLE_CONTRACT": r"check failed: regexp (?:Kelvin tables|long s tables|sharp s tables|surrogate exclusion)",
        "REGEXP_MATCHING_CONTRACT": r"check failed: regexp (?:ICU Unicode closure|Kelvin matching|long s matching|sharp s matching|Greek mu matching|ordinary matching|canonicalization boundaries)",
        "REGEXP_REPRODUCIBILITY": r"check failed: regexp generation path reproducibility",
        "REGEXP_INPUT_FILES": r"check failed: regexp (?:generated file|ambient data access disabled)",
        "PARTITION_ALLOC_OWNERSHIP": r"check failed: PartitionAlloc heap ownership|check failed: PartitionAlloc C\+\+ new value",
        "PARTITION_ALLOC_BYTES": r"check failed: PartitionAlloc preserved bytes",
        "PARTITION_ALLOC_FAILURE_BOUNDARY": r"check failed: PartitionAlloc (?:failed realloc returns null|calloc overflow (?:rejected|traps)|allocation overflow traps|oversized allocation rejected)",
        "PARTITION_ALLOC_CHILD_PROCESS": r"check failed: PartitionAlloc overflow child",
        "PARTITION_ALLOC_ALIGNMENT": r"check failed: PartitionAlloc (?:requested alignment|realloc alignment)",
        "PARTITION_ALLOC_NATIVE_CHECK": r"Check failed:|Check failure",
        "RUST_UNRESOLVED_IMPORT": r"error\[E043[23]\]|unresolved import|unresolved module",
        "RUST_MISSING_CRATE": r"error\[E0463\]|can't find crate for",
        "RUST_TYPE_ERROR": r"error\[E0308\]|error\[E0277\]",
        "RUST_UNSTABLE_OPTION": r"error\[E0554\]|unknown unstable option|feature.*not.*allowed",
        "RUST_BUILD_SCRIPT": r"failed to run custom build command|build script process failed|failed to execute build script",
        "RUST_BUILD_ENV": r"environment variable.*not defined at compile time|OUT_DIR.*not defined|CARGO_MANIFEST_DIR.*not defined",
        "RUST_PROC_MACRO": r"proc-macro panicked|could not load proc macro",
        "RUST_PANIC": r"thread .* panicked at|panic in a function that cannot unwind",
        "BINDGEN_TOOL": r"unable to find libclang|clang diagnosed error|bindgen.*panicked",
        "TEMPORAL_ALLOCATOR": r"check failed: Temporal (?:Rust heap ownership|Rust buffer bytes|Rust unchecked allocation failure|object heap ownership)",
        "TEMPORAL_CALENDAR": r"check failed: Temporal (?:leap date|invalid leap date|constrained date|duration parsing|calendar|Japanese)",
        "TEMPORAL_TIMEZONE": r"check failed: Temporal (?:unknown timezone|timezone parsing|hour duration|DST)",
        "TEMPORAL_ICU_DATA": r"check failed: Temporal declared ICU data",
        "V8_SUPPORT_NUMBER": r"check failed: V8 support number",
        "V8_SUPPORT_UNICODE": r"check failed: V8 support (?:UTF8|UTF16|Unicode|invalid UTF8)",
        "V8_SUPPORT_SIMD": r"check failed: V8 support (?:CPU target|SIMD)",
        "V8_SUPPORT_COMPRESSION": r"check failed: V8 support (?:compression|short output|corrupt compression|checksum)",
        "PROTOBUF_WIRE": r"check failed: Protobuf (?:full|lite|unknown|malformed|truncated|invalid UTF8)",
        "PROTOBUF_REFLECTION": r"check failed: Protobuf (?:dynamic|oneof)",
        "PERFETTO_JSON": r"check failed: Perfetto JsonCpp",
        "PERFETTO_TRACE": r"check failed: Perfetto (?:trace bytes|decoded trace|disabled category)",
        "GENERATOR_REPRODUCIBILITY": r"Generator output differs across source paths and mtimes",
        "GENERATOR_LAYOUT": r"Invalid generator logical path|Duplicate generator logical input|Unresolved generator argument",
        "GENERATOR_PYTHON_IMPORT": r"ModuleNotFoundError:|ImportError:",
        "GENERATOR_TEMPLATE": r"TemplateNotFound|TemplateSyntaxError|jinja2.exceptions",
        "PROTOC_PLUGIN": r"Plugin failed with status code|program not found or is not executable|protoc-gen-plugin:",
        "V8_ENGINE_SCRIPT": r"check failed: V8 engine JavaScript|V8 engine script exception:",
        "V8_ENGINE_INSPECTOR": r"check failed: V8 engine inspector",
        "V8_ENGINE_LIFECYCLE": r"check failed: V8 engine (?:initialization|isolate|disposal)",
        "V8_ENGINE_DATA": r"check failed: V8 engine declared",
        "V8_ENGINE_SYNTAX": r"check failed: V8 engine syntax",
        "V8_ENGINE_COLLECTION": r"check failed: V8 engine context survives",
        "GENERATED_LAYOUT": r"Missing original generated input|Duplicate original generated input|Generated layout output arity differs",
        "ASSERTION_FAILURE": r"AssertionError:",
        "PROCESS_SIGNAL": r"Segmentation fault|SIGSEGV|SIGABRT|Aborted|Illegal instruction|SIGILL|SIGTRAP|Trace/breakpoint trap|Received signal [456711]",
        "RESOURCE_EXHAUSTED": r"Out of memory|ResourceExhausted|OOMKilled",
        "SOURCE_VALIDATION": r"fingerprint mismatch|Patched file differs",
        "EXECUTABLE_NOT_FOUND": r"not found|No such file or directory|ENOENT",
        "EXECUTABLE_PERMISSION": r"Permission denied|EACCES",
        "SHARED_LIBRARY_LOAD": r"error while loading shared libraries|GLIBC_[0-9.]+.*not found",
        "PROCESS_START": r"Failed to start|Could not execute|cannot execute",
        "EXEC_FORMAT": r"exec format error",
    }
    patterns.update({"PARTITION_ALLOC_STAGE_" + stage: "PARTITION_ALLOC_" + stage + r"\b" for stage in ("ENTRY", "ALLOC", "REALLOC", "CALLOC", "ALIGNED", "LIBC", "NEW", "DONE")})
    return {category: len(re.findall(pattern, log, re.IGNORECASE)) for category, pattern in patterns.items() if re.search(pattern, log, re.IGNORECASE)}


def source_test_diagnostics(identifier, key, selected=None):
    probes = {
        "//:loop_consumer_test": "loop_consumer",
        "//source:loop_interrupt_test": "loop_interrupt",
        "//source:crypto_compat_test": "crypto_compat",
        "//source:fuses_test": "fuses",
        "//source:node_defines_test": "node_defines",
        "//source:v8_tasks_test": "v8_tasks",
        "//tests:electron_bundles_test": "electron_bundles",
        "//tests:node_builtins_test": "node_builtins",
        "//source:node_dependencies_test": "node_dependencies",
        "//tests:v8_torque_test": "torque",
        "//source:v8_bytecodes_test": "bytecodes",
        "//source:icu_test": "icu",
        "//source:v8_regexp_test": "regexp",
        "//source:partition_alloc_test": "partition_alloc",
        "//source:temporal_test": "temporal",
        "//source:v8_support_test": "v8_support",
        "//source:protobuf_test": "protobuf",
        "//source:perfetto_test": "perfetto",
        "//source:v8_engine_test": "v8_engine",
        "//source:base_test": "base",
        "//source:libnode_test": "libnode",
        "//source:embedder_test": "embedder",
        "//source:ipcz_test": "ipcz",
        "//source:network_test": "network",
        "//source:mojo_test": "mojo",
        "//source:fonts_test": "fonts",
        "//source:codecs_test": "codecs",
        "//source:skia_test": "skia",
        "//source:gfx_test": "gfx",
        "//source:display_test": "display",
        "//source:events_test": "events",
        "//source:ui_test": "ui",
        "//source:ui_webui_test": "ui_webui",
        "//source:platform_graphics_test": "platform_graphics",
        "//source:gpu_transport_test": "gpu_transport",
        "//source/media:symphonia_test": "symphonia",
        "//source/media:media_runtime_test": "media_runtime",
        "//source/compositor:compositor_test": "compositor",
        "//source/blink_platform:platform_test": "blink_platform",
        "//source/blink_core:core_test": "blink_core",
        "//source/blink_bindings:bindings_test": "blink_bindings",
        "//source/crabbyavif:decode_test": "crabby_decode",
        "//source/blink_rust:font_format_test": "blink_font",
        "//source/blink_rust:crash_test": "blink_crash",
        "//source/media:asound_abi_test": "asound_abi",
        "//electron/private:nss_integrity_test": "nss_integrity",
        "//tests:prepare_source_test": "prepare_source",
    }
    public_files = set(json.loads(Path(__file__).with_name("public_source_files.json").read_text()))
    public_basenames = {path.rsplit("/", 1)[-1] for path in public_files}
    public_checks = json.loads(Path(__file__).with_name("public_probe_checks.json").read_text())
    public_identifiers = set(json.loads(Path(__file__).with_name("public_source_identifiers.json").read_text()))
    results = {}

    def test_result(label):
        if label not in results:
            request = urllib.request.Request("https://formatjs.buildbuddy.io/rpc/BuildBuddyService/GetTarget",
                                             data=json.dumps({"invocation_id": identifier, "target_label": label}).encode(),
                                             headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
                content = response.read(4 * 1024**2 + 1)
            if len(content) > 4 * 1024**2:
                raise ValueError("Test result metadata exceeds limit")
            states = [target.get("testSummary", {}).get("overallStatus", target.get("status")) for group in json.loads(content).get("targetGroups", []) for target in group.get("targets", []) if target.get("metadata", {}).get("label") == label]
            allowed = {"PASSED", "FAILED", "FLAKY", "TIMEOUT", "TIMED_OUT", "INCOMPLETE", "REMOTE_FAILURE", "FAILED_TO_BUILD", "TOOL_FAILED", "CANCELLED"}
            results[label] = states[-1] if states and states[-1] in allowed else "unknown"
        return results[label]

    token, seen, count = "", set(), 0
    for _ in range(8):
        if token in seen:
            break
        seen.add(token)
        with api_request("GetAction", {"selector": {"invocation_id": identifier}, "page_token": token}, key) as response:
            content = response.read(8 * 1024**2 + 1)
        if len(content) > 8 * 1024**2:
            raise ValueError("Test action metadata exceeds limit")
        page = json.loads(content)
        for action in page.get("action", []):
            probe = next((name for suffix, name in probes.items() if action.get("targetLabel", "").endswith(suffix)), None)
            if probe is None or selected is not None and probe not in selected:
                continue
            for file in action.get("file", []):
                if file.get("name", "").rsplit("/", 1)[-1] != "test.log":
                    continue
                if file.get("contents"):
                    data = base64.b64decode(file["contents"], validate=True)
                    if len(data) > 1024**2:
                        raise ValueError("Test log exceeds limit")
                else:
                    uri = file.get("uri", "")
                    parsed = urllib.parse.urlsplit(uri)
                    digest = re.search(r"/blobs/([0-9a-f]{64})/(\d+)$", parsed.path)
                    if parsed.scheme != "bytestream" or parsed.netloc not in ("formatjs.buildbuddy.io", "remote.buildbuddy.io") or not digest or int(digest[2]) > 1024**2:
                        continue
                    with api_request("GetFile", {"uri": uri}, key) as response:
                        data = response.read(int(digest[2]) + 1)
                    if len(data) != int(digest[2]) or hashlib.sha256(data).hexdigest() != digest[1]:
                        raise ValueError("Test log digest mismatch")
                count += 1
                log = data.decode("utf-8", errors="replace")
                details = {"probe": probe, "result": test_result(action["targetLabel"]), "log_bytes": len(data), "diagnostics": classify(log)}
                details["public_missing_shared_libraries"] = sorted({name for name in re.findall(r"error while loading shared libraries: ([A-Za-z0-9_.+-]{1,120}):", log) if name in public_basenames})[:8]
                if probe == "partition_alloc":
                    # Only public source basenames and bounded line numbers leave memory.
                    sites = ["partition_root.h", "partition_root.cc", "partition_alloc.cc", "partition_address_space.h", "partition_address_space.cc", "allocator_shim_default_dispatch_to_partition_alloc.cc", "partition_bucket.cc", "slot_span_metadata.h", "check.h", "thread_cache.cc", "pkey.cc"]
                    details["public_check_sites"] = [{"file": name, "line": int(line)} for name in sites for line in re.findall(r"(?:^|[/\s\[:])" + re.escape(name) + r"[:(]([0-9]{1,4})(?::|\]|\s|\))", log) if 0 < int(line) < 5000][:8]
                if probe in ("partition_alloc", "libnode", "embedder", "ipcz", "network", "mojo", "fonts", "codecs", "skia", "gfx", "display", "events", "ui", "ui_webui", "platform_graphics", "gpu_transport", "symphonia", "media_runtime", "asound_abi", "compositor", "blink_font", "blink_crash", "blink_bindings", "blink_platform", "blink_core", "crabby_decode"):
                    prefix = "patched libnode" if probe == "libnode" else "PartitionAlloc" if probe == "partition_alloc" else probe
                    details["failed_checks"] = [message for message in public_checks.get(probe, []) if "check failed: " + prefix + " " + message + "\n" in log]
                    details["stages"] = [stage for stage in ["entry", "versions", "invalid", "decode", "png", "pixels", "rgb_freed", "image_freed", "conversion", "atomic", "icu", "i18n", "snapshot", "node", "gin", "platform", "isolate", "modules", "integrity", "callback", "gc", "loop", "shutdown", "done"] if probe + " probe stage: " + stage + "\n" in log]
                    details["public_check_sites"] = [{"file": name, "line": int(line)} for name, line in re.findall(r"([A-Za-z_0-9.-]+\.(?:h|c|cc|cpp))[:(]([0-9]{1,5})", log) if name in public_basenames and 0 < int(line) < 10000][:8]
                    fatal = [line for line in log.splitlines() if re.search(r"FATAL|ERROR|Check failed|Assertion|assertion|\b(?:ReferenceError|TypeError|SyntaxError|RangeError|Error):", line)]
                    details["public_fatal_identifiers"] = [list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", line) if word in public_identifiers))[:20] for line in fatal[:6]]
                    details["public_assertion_identifiers"] = [list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression) if word in public_identifiers))[:8] for expression in re.findall(r"assertion failed: ([^\r\n]{1,300})", log)[:4]]
                print("Source probe test diagnostics:", json.dumps(details, sort_keys=True))
        token = page.get("nextPageToken", "")
        if not token:
            break
    print("Source probe logs classified:", count)


def failed_action_diagnostics(identifier, key):
    public_headers = set(json.loads(Path(__file__).with_name("public_source_headers.json").read_text()))
    public_files = set(json.loads(Path(__file__).with_name("public_source_files.json").read_text()))
    public_identifiers = set(json.loads(Path(__file__).with_name("public_source_identifiers.json").read_text()))
    public_basenames = {path.rsplit("/", 1)[-1] for path in public_files}
    for path in public_files:
        if path.endswith((".h", ".hpp", ".inc", ".inl")):
            parts = path.split("/")
            public_headers.update("/".join(parts[index:]) for index in range(len(parts)))
    request = urllib.request.Request("https://formatjs.buildbuddy.io/rpc/BuildBuddyService/GetExecution",
                                     data=json.dumps({"execution_lookup": {"invocation_id": identifier}, "inline_execute_response": True}).encode(),
                                     headers={"Content-Type": "application/json", "x-buildbuddy-api-key": key})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        data = response.read(64 * 1024**2 + 1)
    if len(data) > 64 * 1024**2:
        raise ValueError("Execution diagnostics exceed limit")
    failures = 0
    for execution in json.loads(data).get("execution", []):
        response = execution.get("executeResponse", {})
        result = response.get("result", {})
        status = execution.get("status", {})
        exit_code = result.get("exitCode", execution.get("exitCode", 0))
        if not exit_code and not status.get("code"):
            continue
        failures += 1
        if failures > 32:
            break
        log = status.get("message", "") + response.get("status", {}).get("message", "")
        for name in ("stdoutRaw", "stderrRaw"):
            log += base64.b64decode(result.get(name, ""), validate=True).decode("utf-8", errors="replace")
        digests = [result.get(name) for name in ("stdoutDigest", "stderrDigest")]
        digests += [file.get("digest") for file in result.get("outputFiles", []) if file.get("path", "").rsplit("/", 1)[-1] == "test.log"]
        for digest in digests:
            if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest.get("hash", "")) or not 0 < int(digest.get("sizeBytes", 0)) <= 1024**2:
                continue
            uri = "bytestream://formatjs.buildbuddy.io/blobs/" + digest["hash"] + "/" + str(digest["sizeBytes"])
            with api_request("GetFile", {"uri": uri}, key) as response:
                content = response.read(1024**2 + 1)
            if len(content) > 1024**2:
                raise ValueError("Test log exceeds limit")
            log += content.decode("utf-8", errors="replace")
        # Only exact filenames already present in public source leave memory.
        log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
        missing = {name for name in re.findall(r"fatal error: ['\"]([^'\"\n]+)['\"] file not found", log) if name in public_headers}
        missing_inputs, missing_basenames = set(), set()
        for path in re.findall(r"(?:FileNotFoundError: [^\r\n]*?:\s*|No such file or directory:\s*)b?[\"']([^\"'\r\n]{1,1000})[\"']", log):
            path = posixpath.normpath(path)
            if posixpath.basename(path) in public_basenames:
                missing_basenames.add(posixpath.basename(path))
            candidates = [path]
            for prefix in ("v8/", "third_party/", "gen/", "source/", "build/", "gpu/", "ui/", "cc/", "skia/", "electron/"):
                if "/" + prefix in path:
                    candidates.append(prefix + path.split("/" + prefix, 1)[1])
            parts = path.split("/")
            candidates.extend("/".join(parts[index:]) for index in range(len(parts)))
            missing_inputs.update(name for name in candidates if name in public_files)
        for line in log.splitlines():
            if "FileNotFound" in line:
                missing_basenames.update(name for name in re.findall(r"[A-Za-z0-9_.+-]+\.[A-Za-z0-9]+", line) if name in public_basenames)
        nonreproducible = []
        for script, outputs in re.findall(r"Generator output differs across source paths and mtimes: ([^;\r\n]+); ([^\r\n]+)", log):
            if script in public_files:
                known = [path for path in outputs.split(", ") if path in public_files]
                nonreproducible.append({"script": script, "outputs": known[:8]})
        undefined = []
        for symbol in re.findall(r"undefined symbol: ([^\r\n]+)", log)[:12]:
            identifiers = [word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", symbol) if word in public_identifiers]
            undefined.append(list(dict.fromkeys(identifiers))[:16])
        sites = []
        stack = []
        for path, line in re.findall(r'File "([^"\n]+)", line ([0-9]{1,5})', log):
            known = next((name for name in public_files if path == name or path.endswith("/" + name)), None)
            if known and 0 < int(line) < 10000:
                stack.append({"file": known, "line": int(line)})
        stack = stack[-8:]
        cpp_errors = [list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", message) if word in public_identifiers))[:20] for message in re.findall(r"(?:fatal )?error(?:\[E[0-9]{4}\])?: ([^\r\n]+)", log)[:12]]
        for path, line in re.findall(r"([^\s:]+):([0-9]{1,5}):[0-9]{1,4}: (?:fatal )?error:", log):
            candidates = [path]
            for prefix in ("v8/", "third_party/", "gen/", "src/", "include/", "base/", "source/", "build/", "testing/", "net/", "mojo/", "crypto/", "sql/", "url/", "components/", "electron/", "skia/", "gpu/", "ui/", "cc/"):
                if "/" + prefix in path:
                    candidates.append(prefix + path.split("/" + prefix, 1)[1])
            name = next((name for name in candidates if name in public_files), None)
            if name is not None and 0 < int(line) < 10000:
                sites.append({"file": name, "line": int(line)})
        ts_sites = []
        check_sites = [{"file": name, "line": int(line)} for name, line in re.findall(r"([A-Za-z_0-9.-]+\.(?:h|c|cc|cpp))[:(]([0-9]{1,5})", log) if name in public_basenames and 0 < int(line) < 10000][:8]
        fatal_lines = [line for line in log.splitlines() if re.search(r"FATAL|ERROR|Check failed|Assertion|assertion", line)]
        fatal_identifiers = [list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", line) if word in public_identifiers))[:20] for line in fatal_lines[:6]]
        missing_shared_libraries = sorted({name for name in re.findall(r"error while loading shared libraries: ([A-Za-z0-9_.+-]{1,120}):", log) if name in public_basenames})[:8]
        ts_codes = sorted(set(re.findall(r"\berror (TS[0-9]{4,5}):", log)))[:16]
        ts_locations = re.findall(r"([^\s()]+)\(([0-9]{1,5}),([0-9]{1,4})\): error (TS[0-9]{4,5}):", log)
        ts_locations += re.findall(r"([^\s:]+):([0-9]{1,5}):([0-9]{1,4}) - error (TS[0-9]{4,5}):", log)
        for path, line, column, code in ts_locations:
            path = posixpath.normpath(path)
            candidates = [path]
            for prefix in ("third_party/", "gen/", "ui/", "tools/", "components/"):
                if "/" + prefix in path:
                    candidates.append(prefix + path.split("/" + prefix, 1)[1])
            known = next((name for name in candidates if name in public_files), None)
            if known and 0 < int(line) < 10000 and 0 < int(column) < 10000:
                ts_sites.append({"file": known, "line": int(line), "column": int(column), "code": code})
        print("Failed action diagnostics:", json.dumps({"exit_code": exit_code, "status_code": status.get("code", 0), "inline_result": bool(result), "log_bytes": len(log.encode()), "diagnostics": classify(log), "public_missing_headers": sorted(missing)[:8], "public_error_sites": sites[:8], "public_python_sites": stack[:8], "public_cpp_error_identifiers": cpp_errors, "public_undefined_identifiers": undefined, "public_missing_inputs": sorted(missing_inputs)[:8], "public_missing_input_basenames": sorted(missing_basenames)[:8], "public_nonreproducible_outputs": nonreproducible[:8], "typescript_error_codes": ts_codes, "public_typescript_sites": ts_sites[:8], "public_check_sites": check_sites, "public_fatal_identifiers": fatal_identifiers, "public_missing_shared_libraries": missing_shared_libraries}, sort_keys=True))


if __name__ == "__main__":
    key = os.environ["BUILDBUDDY_API_KEY"]
    sha = os.environ["BUILD_SHA"]
    if not key or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Read-only key and exact commit SHA required")
    identifier = invocation_id(os.environ["INVOCATION_URL"])

    def invocation(identifier):
        with api_request("GetInvocation", {"selector": {"invocation_id": identifier}, "include_child_invocations": True, "include_artifacts": True}, key) as response:
            values = json.load(response).get("invocation", [])
        if len(values) != 1 or values[0].get("commitSha") != sha or values[0].get("repoUrl", "").removesuffix(".git") != "https://github.com/formatjs/electron":
            raise ValueError("Expected Electron source-overlay repository and commit")
        return values[0]

    root = invocation(identifier)
    if root.get("pattern") not in ("Electron source components", "Electron source cross-compile", "Electron BCR consumer"):
        raise ValueError("Expected an Electron source-overlay CI workflow")
    log = read_log({"invocation_id": identifier}, key)
    print("Source workflow diagnostics:", json.dumps({"log_bytes": len(log.encode()), "diagnostics": classify(log)}, sort_keys=True))
    source_profile_diagnostics(root, key)
    for child in root.get("childInvocations", [])[:32]:
        identifier = child["invocationId"]
        value = invocation(identifier)
        log = read_log({"invocation_id": identifier}, key)
        status = {"COMPLETE_INVOCATION_STATUS": "complete", "PARTIAL_INVOCATION_STATUS": "running", "DISCONNECTED_INVOCATION_STATUS": "disconnected"}.get(value.get("invocationStatus"), "unknown")
        duration = int(value.get("durationUsec", 0))
        if not 0 <= duration <= 7 * 24 * 3600 * 1000000:
            raise ValueError("Source phase duration exceeds limit")
        command = value.get("command") if value.get("command") in ("build", "test") else "unknown"
        print("Source child:", json.dumps({"id": identifier, "state": status, "command": command, "duration_usec": duration, "success": value.get("success") is True, "log_bytes": len(log.encode()), "diagnostics": classify(log)}, sort_keys=True))
        resource_diagnostics(identifier, key)
        if value.get("invocationStatus") == "COMPLETE_INVOCATION_STATUS" and not value.get("success"):
            failed_action_diagnostics(identifier, key)
            source_test_diagnostics(identifier, key)
        elif value.get("invocationStatus") == "COMPLETE_INVOCATION_STATUS" and command == "test":
            source_test_diagnostics(identifier, key, {"symphonia", "gpu_transport", "platform_graphics", "media_runtime", "asound_abi", "compositor", "blink_font", "blink_crash", "blink_bindings", "blink_platform", "blink_core", "crabby_decode"})
