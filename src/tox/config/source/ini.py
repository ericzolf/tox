"""Load """
from __future__ import annotations

from collections import defaultdict
from configparser import ConfigParser
from itertools import chain
from pathlib import Path
from typing import DefaultDict, Iterable, Iterator

from tox.config.loader.ini.factor import find_envs

from ..loader.api import OverrideMap
from ..loader.ini import IniLoader
from ..loader.section import Section
from ..sets import ConfigSet
from .api import Source
from .ini_section import CORE, TEST_ENV_PREFIX, IniSection


class IniSource(Source):
    """Configuration sourced from a ini file (such as tox.ini)"""

    CORE_SECTION = CORE

    def __init__(self, path: Path, content: str | None = None) -> None:
        super().__init__(path)
        self._parser = ConfigParser(interpolation=None)
        if content is None:
            if not path.exists():
                raise ValueError
            content = path.read_text()
        self._parser.read_string(content, str(path))
        self._section_mapping: DefaultDict[str, list[str]] = defaultdict(list)

    def transform_section(self, section: Section) -> Section:
        return IniSection(section.prefix, section.name)

    def sections(self) -> Iterator[IniSection]:
        for section in self._parser.sections():
            yield IniSection.from_key(section)

    def get_loader(self, section: Section, override_map: OverrideMap) -> IniLoader | None:
        sections = self._section_mapping.get(section.name)
        key = sections[0] if sections else section.key
        if self._parser.has_section(key):
            return IniLoader(
                section=section,
                parser=self._parser,
                overrides=override_map.get(section.key, []),
                core_section=self.CORE_SECTION,
                section_key=key,
            )
        return None

    def get_core_section(self) -> Section:
        return self.CORE_SECTION

    def get_base_sections(self, base: list[str], in_section: Section) -> Iterator[Section]:
        for a_base in base:
            section = IniSection.from_key(a_base)
            yield section  # the base specifier is explicit
            if in_section.prefix is not None:  # no prefix specified, so this could imply our own prefix
                yield IniSection(in_section.prefix, a_base)

    def get_tox_env_section(self, item: str) -> tuple[Section, list[str]]:
        return IniSection.test_env(item), [TEST_ENV_PREFIX]

    def envs(self, core_config: ConfigSet) -> Iterator[str]:
        seen = set()
        for name in self._discover_tox_envs(core_config):
            if name not in seen:
                seen.add(name)
                yield name

    def _discover_tox_envs(self, core_config: ConfigSet) -> Iterator[str]:
        def register_factors(envs: Iterable[str]) -> None:
            known_factors.update(chain.from_iterable(e.split("-") for e in envs))

        explicit = list(core_config["env_list"])
        yield from explicit
        known_factors: set[str] = set()
        register_factors(explicit)

        # discover all additional defined environments, including generative section headers
        for section in self.sections():
            register_factors(section.names)
            for name in section.names:
                self._section_mapping[name].append(section.key)
                if section.is_test_env:
                    yield name
        # add all conditional markers that are not part of the explicitly defined sections
        for section in self.sections():
            yield from self._discover_from_section(section, known_factors)

    def _discover_from_section(self, section: IniSection, known_factors: set[str]) -> Iterator[str]:
        for value in self._parser[section.key].values():
            for env in find_envs(value):
                if set(env.split("-")) - known_factors:
                    yield env

    def __repr__(self) -> str:
        return f"{type(self).__name__}(path={self.path})"


__all__ = [
    "IniSource",
]
