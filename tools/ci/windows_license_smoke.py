"""Check consent controls on the BB-built installer; cancel before installing."""

import ctypes
from ctypes import wintypes
import subprocess
import time


def smoke_license(installer):
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetDlgItem.restype = wintypes.HWND
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsWindowEnabled.argtypes = [wintypes.HWND]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = wintypes.LPARAM

    def message(window, code, word=0, parameter=0):
        result = ctypes.c_size_t()
        if not user.SendMessageTimeoutW(window, code, word, parameter, 3, 2000, ctypes.byref(result)):
            raise RuntimeError('NSIS_LICENSE_CONTROL_TIMEOUT')
        return result.value

    def text(window):
        buffer = ctypes.create_unicode_buffer(65536)
        try:
            message(window, 0x000D, len(buffer), ctypes.addressof(buffer))
        except RuntimeError:
            if not user.IsWindow(window):
                return ''
            raise
        return buffer.value

    def click(window):
        if not user.PostMessageW(window, 0x00F5, 0, 0):
            raise RuntimeError('NSIS_LICENSE_CONTROL_FAILED')

    def windows(process):
        found = []

        @callback_type
        def collect(window, unused):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == process.pid and user.IsWindowVisible(window):
                found.append(window)
            return True

        user.EnumWindows(collect, 0)
        return found

    def controls(window):
        found = []

        @callback_type
        def collect(child, unused):
            if user.IsWindowVisible(child):
                found.append(child)
            return True

        user.EnumChildWindows(window, collect, 0)
        return found

    def wait_for(process, predicate):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            if process.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError('NSIS_LICENSE_STATE_TIMEOUT')

    def select_language(process, language):
        for window in windows(process):
            for control in controls(window):
                name = ctypes.create_unicode_buffer(256)
                user.GetClassNameW(control, name, len(name))
                if name.value != 'ComboBox':
                    continue
                count = message(control, 0x0146)
                if count != 2:
                    continue
                if language is None:
                    button = user.GetDlgItem(window, 2)
                    if button and user.IsWindowEnabled(button):
                        click(button)
                        return True
                    continue
                label = ctypes.create_unicode_buffer(language)
                index = message(control, 0x0158, -1, ctypes.addressof(label))
                if index >= count:
                    continue
                message(control, 0x014E, index)
                if message(control, 0x0147) != index:
                    raise RuntimeError('NSIS_LICENSE_LANGUAGE_SELECTION_FAILED')
                button = user.GetDlgItem(window, 1)
                if button and user.IsWindowEnabled(button):
                    click(button)
                    return True

    def license_window(process, language):
        for window in windows(process):
            for control in controls(window):
                body = text(control)
                locale = {'English': 'en_US', 'Japanese': 'ja_JP'}[language]
                if ('Sample Desktop example license, version 1.' in body and 'Example Unicode text: 世界 😀.' in body
                        and 'License locale: ' + locale + '.' in body):
                    return window

    def checked_control(window):
        for control in controls(window):
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(control, name, len(name))
            if name.value == 'Button' and (user.GetWindowLongW(control, -16) & 15) in (2, 3):
                return control
        raise RuntimeError('NSIS_LICENSE_CHECKBOX_MISSING')

    for language, accept in ((language, accept) for language in ('English', 'Japanese') for accept in (False, True)):
        process = subprocess.Popen([str(installer)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for(process, lambda: select_language(process, language))
            window = wait_for(process, lambda: license_window(process, language))
            next_button = user.GetDlgItem(window, 1)
            checkbox = checked_control(window)
            if not next_button or user.IsWindowEnabled(next_button) or message(checkbox, 0x00F0):
                raise RuntimeError('NSIS_LICENSE_NOT_REQUIRED')
            if accept:
                click(checkbox)
                wait_for(process, lambda: user.IsWindowEnabled(next_button))
                click(next_button)
                wait_for(process, lambda: not license_window(process, language))
            cancel = user.GetDlgItem(window, 2)
            if not cancel:
                raise RuntimeError('NSIS_LICENSE_CANCEL_MISSING')
            click(cancel)

            def confirm_cancel():
                if process.poll() is not None:
                    return True
                for dialog in windows(process):
                    yes = user.GetDlgItem(dialog, 6)
                    if yes and user.IsWindowVisible(yes):
                        click(yes)
                        return True

            wait_for(process, confirm_cancel)
            if process.wait(timeout=30) != 1:
                raise RuntimeError('NSIS_LICENSE_CANCEL_FAILED')
            print('NSIS_LICENSE_LANGUAGE_OK ' + language + ' ' + ('accepted' if accept else 'declined'), flush=True)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    process = subprocess.Popen([str(installer)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(process, lambda: select_language(process, None))
        if process.wait(timeout=30) != 1:
            raise RuntimeError('NSIS_LICENSE_LANGUAGE_CANCEL_FAILED')
        print('NSIS_LICENSE_LANGUAGE_CANCEL_OK', flush=True)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    print('NSIS_LICENSE_CONSENT_OK', flush=True)
