from utils.logger import logger
import json
import os
from typing import Dict, Optional
import config
LANG_DIR_REL = config.LANG_DIR_REL


class LanguageManager:
    def __init__(self, languages_dir: str = "lang"):
        self.languages_dir = languages_dir
        self.languages: Dict[str, Dict] = {}
        self.default_language = "en"
        self.load_languages()

    def load_languages(self):
        try:
            if not os.path.exists(self.languages_dir):
                logger.warning(f"Languages directory {self.languages_dir} not found")
                return

            for filename in os.listdir(self.languages_dir):
                if filename.endswith(".json"):
                    language_code = filename[:-5]  # Remove .json extension
                    file_path = os.path.join(self.languages_dir, filename)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            self.languages[language_code] = json.load(f)
                        logger.info(f"Successfully loaded language: {language_code}")
                    except Exception as e:
                        logger.error(f"Error loading language file {filename}: {e}")

            if not self.languages:
                logger.warning("No language files found")
            elif self.default_language not in self.languages:
                logger.warning(f"Default language {self.default_language} not found")
        except Exception as e:
            logger.error(f"Error loading languages: {e}")

    def get_text(self, key: str, language_code: Optional[str] = None, **kwargs) -> str:
        try:
            if not language_code or language_code not in self.languages:
                language_code = self.default_language

            language = self.languages[language_code]
            text = language.get(key)

            if not text:
                logger.warning(
                    f"Translation key '{key}' not found in language " f"{language_code}"
                )
                # Try to get from default language
                if language_code != self.default_language:
                    text = self.languages[self.default_language].get(key)
                    if not text:
                        # If kwargs are provided, use the default message from the
                        # handler
                        if kwargs and "default" in kwargs:
                            return kwargs["default"]
                        return key  # Return the key if not found anywhere

            # Replace placeholders with provided values
            if kwargs:
                try:
                    text = text.format(**kwargs)
                except KeyError as e:
                    logger.error(f"Missing placeholder in translation key '{key}': {e}")
                    return key

            return text
        except Exception as e:
            logger.error(f"Error getting text for key '{key}': {e}")
            # If kwargs are provided, use the default message from the handler
            if kwargs and "default" in kwargs:
                return kwargs["default"]
            return key

    def get_available_languages(self) -> Dict[str, str]:
        try:
            return {
                code: data.get("language_name", code)
                for code, data in self.languages.items()
            }
        except Exception as e:
            logger.error(f"Error getting available languages: {e}")
            return {}

    def add_language(self, language_code: str, translations: Dict):
        try:
            self.languages[language_code] = translations
            file_path = os.path.join(self.languages_dir, f"{language_code}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)
            logger.info(f"Successfully added language: {language_code}")
        except Exception as e:
            logger.error(f"Error adding language {language_code}: {e}")

    def update_language(self, language_code: str, translations: Dict):
        try:
            if language_code not in self.languages:
                logger.warning(f"Language {language_code} not found, adding it")
                self.add_language(language_code, translations)
                return

            self.languages[language_code].update(translations)
            file_path = os.path.join(self.languages_dir, f"{language_code}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    self.languages[language_code], f, ensure_ascii=False, indent=2
                )
            logger.info(f"Successfully updated language: {language_code}")
        except Exception as e:
            logger.error(f"Error updating language {language_code}: {e}")

    def remove_language(self, language_code: str):
        try:
            if language_code == self.default_language:
                logger.warning(f"Cannot remove default language {language_code}")
                return

            if language_code in self.languages:
                del self.languages[language_code]
                file_path = os.path.join(self.languages_dir, f"{language_code}.json")
                if os.path.exists(file_path):
                    os.remove(file_path)
                logger.info(f"Successfully removed language: {language_code}")
            else:
                logger.warning(f"Language {language_code} not found")
        except Exception as e:
            logger.error(f"Error removing language {language_code}: {e}")


# Create a singleton instance
_language_manager = LanguageManager(config.LANG_DIR_REL)


def get_string(key: str, language_code: Optional[str] = None, **kwargs) -> str:
    """
    Get a localized string for the given key and language code.

    Args:
        key: The translation key to look up
        language_code: Optional language code (defaults to 'en')
        **kwargs: Optional format parameters for the string

    Returns:
        The localized string, or the key if not found
    """
    return _language_manager.get_text(key, language_code, **kwargs)


def load_languages(languages_dir: str = "languages"):
    """
    Reload all language files.

    Args:
        languages_dir: Path to the directory containing language files
    """
    _language_manager.languages_dir = languages_dir
    _language_manager.load_languages()
