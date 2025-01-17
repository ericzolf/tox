"""
A tox build environment that handles Python packages.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator, Iterator, Sequence, cast

from packaging.requirements import Requirement

from ...config.sets import EnvConfigSet
from ..api import ToxEnvCreateArgs
from ..errors import Skip
from ..package import Package, PackageToxEnv, PathPackage
from ..runner import RunToxEnv
from .api import Python
from .pip.req_file import PythonDeps

if TYPE_CHECKING:
    from tox.config.main import Config


class PythonPackage(Package):
    """python package"""


class PythonPathPackageWithDeps(PathPackage):
    def __init__(self, path: Path, deps: Sequence[Any]) -> None:
        super().__init__(path=path)
        self.deps: Sequence[Package] = deps


class WheelPackage(PythonPathPackageWithDeps):
    """wheel package"""


class SdistPackage(PythonPathPackageWithDeps):
    """sdist package"""


class EditableLegacyPackage(PythonPathPackageWithDeps):
    """legacy editable package"""


class EditablePackage(PythonPathPackageWithDeps):
    """PEP-660 editable package"""


class PythonPackageToxEnv(Python, PackageToxEnv, ABC):
    def __init__(self, create_args: ToxEnvCreateArgs) -> None:
        self._wheel_build_envs: dict[str, PythonPackageToxEnv] = {}
        super().__init__(create_args)

    def _setup_env(self) -> None:
        """setup the tox environment"""
        super()._setup_env()
        self.installer.install(self.requires(), PythonPackageToxEnv.__name__, "requires")

    @abstractmethod
    def requires(self) -> tuple[Requirement, ...] | PythonDeps:
        raise NotImplementedError

    def register_run_env(self, run_env: RunToxEnv) -> Generator[tuple[str, str], PackageToxEnv, None]:
        yield from super().register_run_env(run_env)
        if (
            not isinstance(run_env, Python)
            or run_env.conf["package"] not in {"wheel", "editable"}
            or "wheel_build_env" in run_env.conf
        ):
            return

        def default_wheel_tag(conf: Config, env_name: str | None) -> str:  # noqa: U100
            # https://www.python.org/dev/peps/pep-0427/#file-name-convention
            # when building wheels we need to ensure that the built package is compatible with the target env
            # compatibility is documented within https://www.python.org/dev/peps/pep-0427/#file-name-convention
            # a wheel tag example: {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
            # python only code are often compatible at major level (unless universal wheel in which case both 2/3)
            # c-extension codes are trickier, but as of today both poetry/setuptools uses pypa/wheels logic
            # https://github.com/pypa/wheel/blob/master/src/wheel/bdist_wheel.py#L234-L280
            run_py = cast(Python, run_env).base_python
            if run_py is None:
                base = ",".join(run_env.conf["base_python"])
                raise Skip(f"could not resolve base python with {base}")

            default_pkg_py = self.base_python
            if (
                default_pkg_py.version_no_dot == run_py.version_no_dot
                and default_pkg_py.impl_lower == run_py.impl_lower
            ):
                return self.conf.name

            return f"{self.conf.name}-{run_py.impl_lower}{run_py.version_no_dot}"

        run_env.conf.add_config(
            keys=["wheel_build_env"],
            of_type=str,
            default=default_wheel_tag,
            desc="wheel tag to use for building applications",
        )
        pkg_env = run_env.conf["wheel_build_env"]
        result = yield pkg_env, run_env.conf["package_tox_env_type"]
        self._wheel_build_envs[pkg_env] = cast(PythonPackageToxEnv, result)

    def child_pkg_envs(self, run_conf: EnvConfigSet) -> Iterator[PackageToxEnv]:
        if run_conf["package"] == "wheel":
            env = self._wheel_build_envs.get(run_conf["wheel_build_env"])
            if env is not None and env.name != self.name:
                yield env

    def _teardown(self) -> None:
        for env in self._wheel_build_envs.values():
            if env is not self:
                with env.display_context(self._has_display_suspended):
                    env.teardown()
        super()._teardown()
