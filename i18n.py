import os
import json
import locale


class I18nManager:
    SUPPORTED_LOCALES = {
        "zh_CN": "简体中文",
        "en_US": "English",
    }

    def __init__(self, locales_dir=None, config_file=None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.locales_dir = locales_dir or os.path.join(base_dir, "locales")
        self.config_file = config_file or os.path.join(base_dir, "config.json")
        self._translations = {}
        self._callbacks = []

        self._load_all_locales()

        # Determine initial locale
        saved_locale = self._load_saved_locale()
        if saved_locale and saved_locale in self.SUPPORTED_LOCALES:
            self.current_locale = saved_locale
        else:
            self.current_locale = self._detect_system_locale()

    def _detect_system_locale(self):
        try:
            sys_loc = locale.getdefaultlocale()[0]
            if sys_loc and sys_loc.lower().startswith("zh"):
                return "zh_CN"
        except Exception:
            pass
        return "en_US"

    def _load_saved_locale(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("locale")
            except Exception:
                pass
        return None

    def _save_locale(self, locale_code):
        try:
            data = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["locale"] = locale_code
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_all_locales(self):
        for loc_code in self.SUPPORTED_LOCALES:
            file_path = os.path.join(self.locales_dir, f"{loc_code}.json")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._translations[loc_code] = json.load(f)
                except Exception:
                    self._translations[loc_code] = {}
            else:
                self._translations[loc_code] = {}

    def set_locale(self, locale_code, notify=True):
        if locale_code not in self.SUPPORTED_LOCALES:
            return
        self.current_locale = locale_code
        self._save_locale(locale_code)
        if notify:
            for cb in self._callbacks:
                try:
                    cb(locale_code)
                except Exception:
                    pass

    def get_locale(self):
        return self.current_locale

    def register_callback(self, callback):
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _lookup(self, loc_code, key_path):
        data = self._translations.get(loc_code, {})
        parts = key_path.split(".")
        curr = data
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return None
        return curr if isinstance(curr, str) else None

    def t(self, key_path, default=None, **kwargs):
        val = self._lookup(self.current_locale, key_path)
        if val is None and self.current_locale != "en_US":
            val = self._lookup("en_US", key_path)
        if val is None:
            val = default if default is not None else key_path

        if kwargs and isinstance(val, str):
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val


i18n = I18nManager()
t = i18n.t
