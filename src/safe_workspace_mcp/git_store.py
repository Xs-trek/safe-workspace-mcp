"""Managed local Git history via Dulwich (no git.exe, no subprocess, no remotes).

Semantics:
* The repo lives in <workspace>/.git and is created on first start
  (refused if one already exists). Plain files MCP can touch are all
  tracked; internal/excluded directories are never tracked.
* checkpoint() snapshots the current working tree state, whatever it is
  (the user may have edited files between MCP transactions).
* Every tracked file is recoverable: Editable => Recoverable.
* No remote is ever created or contacted; Repo.get_config() policy is
  enforced by never touching remote APIs at all.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dulwich import porcelain
from dulwich.hooks import Hook as _DulwichHook
from dulwich.repo import Repo

from . import errors
from .config import Config
from .path_guard import PathGuard

if TYPE_CHECKING:
    from dulwich.objects import ObjectID, Tree
    from dulwich.refs import Ref

_STAT_REPARSE = 0x400

# Managed-repository identity: a dedicated git config key inside .git.
# Purpose is mistake-proofing (never accidentally adopting an external
# repository), NOT cryptographic authentication of the repository owner.
# A git config key may only contain alphanumeric characters and '-', so
# the on-disk form is:  [safe-workspace-mcp] managed-repository-format = 1
_MANAGED_SECTION = b"safe-workspace-mcp"
_MANAGED_KEY = b"managed-repository-format"
_SUPPORTED_FORMATS = frozenset({b"1"})


def _try_remove_git_dir(git_dir: Path) -> None:
    """Best-effort removal of a .git created by the current init call.

    Only ever called right after our own failed Repo.init + marker write;
    a foreign repository cannot be at this path (existence was checked at
    entry), so removal cannot destroy user repositories.
    """
    import shutil

    try:
        shutil.rmtree(git_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001, S110 - cleanup must never mask the real error
        pass


def _hook_noop(self: object, *args: object, **kwargs: object) -> None:
    return None


# SECURITY (module import time, before any repo is opened): neutralize
# dulwich's git-hook execution for every Hook subclass in this process.
#
# Concrete attack path this blocks: dulwich's worktree commit path calls
# hooks["post-commit"].execute() UNCONDITIONALLY on every commit (it is
# not covered by no_verify=True), which attempts subprocess.call on
# <root>/.git/hooks/<name>. If an executable file were ever placed there
# (e.g. a PE binary renamed without extension - Windows CreateProcess
# loads those), every checkpoint() would run it. First line of defense is
# PathGuard (.git is unreachable from every tool); this patch is the
# second, independent layer. The managed repo itself never installs
# hooks. Instance-level patching is insufficient because porcelain
# reopens the repo by path. Verified by test_hooks_never_execute.
import dulwich.hooks as _dulwich_hooks_module  # noqa: E402

for _obj in list(vars(_dulwich_hooks_module).values()):
    if isinstance(_obj, type) and issubclass(_obj, _DulwichHook) and _obj is not _DulwichHook:
        _obj.execute = _hook_noop  # type: ignore[method-assign]


@dataclass(frozen=True)
class CheckpointInfo:
    id: str
    message: str
    timestamp: int


class GitStore:
    """Owns the .git directory; the only component allowed to touch it."""

    def __init__(self, config: Config, guard: PathGuard) -> None:
        self._config = config
        self._guard = guard
        self._repo: Repo | None = None
        self._author = f"{config.git.author_name} <{config.git.author_email}>"

    # --------------------------------------------------------- lifecycle

    def open_or_init_managed(self) -> str | None:
        """Single production entry for the managed-repo lifecycle.

        * no .git            -> create managed repo (marker written before
                                 the initial snapshot) + initial snapshot;
                                 returns the first checkpoint id
        * .git is a verifiably Safe Workspace MCP managed repo
                             -> reopen it; returns None (no new checkpoint)
        * anything else      -> ExistingGitRepoError (fail closed; foreign
                                repositories are never adopted)

        Ownership authority lives HERE (Python MCP core), not in any
        launcher; the marker is checked on every reopen.
        """
        root = self._guard.root
        git_dir = root / ".git"
        if git_dir.exists():
            self._open_managed_existing()
            return None
        repo = Repo.init(str(root), mkdir=False)
        self._repo = repo
        try:
            # Pin line-ending handling: the managed repo must never rewrite
            # file contents on checkout, regardless of the user's global git
            # config (core.autocrlf / core.eol are pinned OFF locally).
            config = repo.get_config()
            config.set(b"core", b"autocrlf", b"false")
            config.set(b"core", b"eol", b"lf")
            # Managed-repository identity, written BEFORE the first commit:
            # if anything below fails, cleanup can safely remove a .git that
            # carries our marker (or no state at all) without ever touching
            # a foreign repository.
            config.set(_MANAGED_SECTION, _MANAGED_KEY, b"1")
            config.write_to_path()
            if self._list_remotes(repo):
                raise errors.GitError_("unexpected remote configuration")
            return self.checkpoint("initial snapshot")
        except Exception:
            # Best-effort rollback of the .git created by THIS call only
            # (its absence was checked at entry). Keeps fail-closed: a
            # half-initialized marker-less .git would otherwise wedge the
            # workspace forever; we never delete anything we did not create.
            self.close()
            _try_remove_git_dir(git_dir)
            raise

    def _open_managed_existing(self) -> None:
        """Attach to a repo previously created by open_or_init_managed().

        Fail closed (ExistingGitRepoError) unless the repository proves it
        is ours: openable, no remotes, valid managed marker with a
        supported format version. Foreign `git init` repos - with or
        without remotes - are rejected, not adopted.
        """
        git_dir = self._guard.root / ".git"
        if not git_dir.is_dir():
            raise errors.ExistingGitRepoError(
                "workspace contains .git that is not a directory; refusing to start"
            )
        try:
            repo = Repo(str(self._guard.root))
        except Exception as exc:  # noqa: BLE001 - unreadable/corrupt -> refuse
            raise errors.ExistingGitRepoError(
                "workspace .git cannot be opened as a Git repository; refusing to adopt"
            ) from exc
        self._repo = repo
        try:
            if self._list_remotes(repo):
                raise errors.ExistingGitRepoError(
                    "existing repository has remotes; managed repositories never do"
                )
            self._verify_managed_identity(repo)
        except errors.ExistingGitRepoError:
            repo.close()
            self._repo = None
            raise
        except Exception as exc:  # noqa: BLE001
            repo.close()
            self._repo = None
            raise errors.ExistingGitRepoError(
                f"managed repository validation failed: {exc}"
            ) from exc

    def _verify_managed_identity(self, repo: Repo) -> None:
        try:
            value = repo.get_config().get(_MANAGED_SECTION, _MANAGED_KEY)
        except Exception:  # noqa: BLE001 - missing section/key/parse error
            value = None
        if not isinstance(value, bytes) or value not in _SUPPORTED_FORMATS:
            raise errors.ExistingGitRepoError(
                "workspace .git is not a Safe Workspace MCP managed repository "
                "(managed marker missing or unsupported format version); "
                "adopting existing repositories is not supported"
            )

    def close(self) -> None:
        if self._repo is not None:
            self._repo.close()
            self._repo = None

    @property
    def repo(self) -> Repo:
        if self._repo is None:
            raise errors.GitError_("git store is not open")
        return self._repo

    def _list_remotes(self, repo: Repo) -> list[str]:
        try:
            config = repo.get_config()
            return [
                section[1].decode()
                for section in config.sections()
                if section[0] == b"remote"
            ]
        except Exception:  # noqa: BLE001 - fail closed on any config anomaly
            return ["<unreadable-config>"]

    # --------------------------------------------------------- checkpoint

    def _iter_managed_paths(self) -> list[Path]:
        """Regular files to track; never internal/excluded; no links."""
        out: list[Path] = []
        stack = [self._guard.root]
        while stack:
            current = stack.pop()
            with os.scandir(current) as it:
                for entry in it:
                    if self._guard.is_internal_or_excluded_dir(entry.name):
                        continue
                    if entry.name.startswith(".mcp-tmp-") and entry.name.endswith(".tmp"):
                        continue  # crash-leftover atomic-write temp files
                    try:
                        st = entry.stat(follow_symlinks=False)
                        mode = st.st_mode
                        reparse = getattr(st, "st_file_attributes", 0) & _STAT_REPARSE
                        if stat.S_ISLNK(mode) or reparse:
                            continue
                        if stat.S_ISDIR(mode):
                            stack.append(Path(entry.path))
                        elif stat.S_ISREG(mode):
                            out.append(Path(entry.path))
                    except OSError:
                        continue
        return out

    def checkpoint(self, message: str) -> str:
        """Snapshot current managed state. Returns checkpoint id.

        no_verify=True is SECURITY-CRITICAL: it stops dulwich from
        attempting to execute .git hooks via subprocess.call (dulwich tries
        this even when no hook file exists). The managed repo never has
        hooks; skipping them is both correct and keeps the no-subprocess
        invariant.
        """
        repo = self.repo
        try:
            self._stage_managed()
            cid = porcelain.commit(
                repo.path,
                message=message.encode("utf-8")[:200],
                author=self._author.encode("utf-8"),
                committer=self._author.encode("utf-8"),
                no_verify=True,
            )
        except errors.SafeWorkspaceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"checkpoint failed: {exc}") from exc
        return cid.decode() if isinstance(cid, bytes) else str(cid)

    # --------------------------------------------------------- queries

    def history(self, limit: int) -> list[CheckpointInfo]:
        repo = self.repo
        out: list[CheckpointInfo] = []
        try:
            walker = repo.get_walker(max_entries=limit)
            for entry in walker:
                c = entry.commit
                out.append(
                    CheckpointInfo(
                        id=c.id.decode(),
                        message=c.message.decode("utf-8", "replace").strip(),
                        timestamp=c.commit_time,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"history failed: {exc}") from exc
        return out

    def status(self) -> dict[str, list[str]]:
        """Working tree changes vs HEAD (managed paths only)."""
        repo = self.repo

        def rel(p: bytes | str) -> str:
            return p.decode() if isinstance(p, bytes) else str(p)

        try:
            staged, unstaged, untracked = porcelain.status(repo.path)
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"status failed: {exc}") from exc
        return {
            "added": sorted(rel(p) for p in staged["add"] + list(untracked)),
            "modified": sorted(
                set(rel(p) for p in staged["modify"] + list(unstaged))
            ),
            "removed": sorted(rel(p) for p in staged["delete"]),
        }

    def diff(self, checkpoint_id: str | None) -> str:
        """Unified diff of the working tree against a checkpoint (or HEAD).

        Implementation: stage current managed files into a temporary tree
        (objects are content-addressed; staging makes nothing dirty), then
        diff_tree(old=checkpoint tree, new=temp tree).
        """
        import io
        from typing import cast

        from dulwich.objects import Commit as DulwichCommit

        repo = self.repo
        try:
            if checkpoint_id is None:
                head = repo.head()
                target = cast(DulwichCommit, repo.object_store[head]).tree
            else:
                cid = self._resolve(checkpoint_id)
                target = cast(DulwichCommit, repo.object_store[cid]).tree
            self._stage_managed()
            new_tree = repo.open_index().commit(repo.object_store)
            buf = io.BytesIO()
            porcelain.diff_tree(repo, target, new_tree, outstream=buf)
            return buf.getvalue().decode("utf-8", "replace")
        except errors.CheckpointNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"diff failed: {exc}") from exc

    def _stage_managed(self) -> None:
        paths = self._iter_managed_paths()
        porcelain.add(
            self.repo.path,
            paths=[
                p.relative_to(self._guard.root).as_posix() for p in paths
            ],
        )

    def _resolve(self, checkpoint_id: str) -> ObjectID:
        repo = self.repo
        try:
            if 6 <= len(checkpoint_id) <= 40 and all(
                c in "0123456789abcdefABCDEF" for c in checkpoint_id
            ):
                prefix = checkpoint_id.lower()
                matches = [
                    entry.commit.id
                    for entry in repo.get_walker(max_entries=10_000)
                    if entry.commit.id.decode().lower().startswith(prefix)
                ]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    raise errors.CheckpointNotFoundError("ambiguous checkpoint id")
            raise errors.CheckpointNotFoundError(f"unknown checkpoint: {checkpoint_id}")
        except errors.CheckpointNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"checkpoint lookup failed: {exc}") from exc

    # --------------------------------------------------------- restore

    def restore(self, checkpoint_id: str, *, pre_restore_checkpoint: str) -> None:
        """Restore workspace managed files to checkpoint state.

        The caller snapshots current state first (checkpoint()), then calls
        this. Implementation: working tree files are synced exactly to the
        target tree (restores modified and deleted files, removes files
        that did not exist at the target), the branch ref is re-pointed to
        the pre-restore checkpoint so history stays linear and every
        checkpoint remains reachable, and a post-restore commit records
        the restored state on top of the chain.
        """
        repo = self.repo
        target = self._resolve(checkpoint_id)
        pre = self._resolve(pre_restore_checkpoint)
        try:
            self.sync_working_tree_to_commit(target)
            branch_ref = self._current_branch_ref()
            branch = branch_ref or b"refs/heads/master"
            from dulwich.refs import Ref

            repo.refs.set_if_equals(Ref(branch), repo.head(), pre)
            repo.refs.set_symbolic_ref(Ref(b"HEAD"), Ref(branch))
            # Post-restore checkpoint: record the restored state on top of
            # the chain so history stays linear and status is clean.
            self.checkpoint(f"restored to {checkpoint_id[:12]}")
        except errors.CheckpointNotFoundError:
            raise
        except errors.GitError_:
            raise
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"restore failed: {exc}") from exc

    def sync_working_tree_to(self, checkpoint_id: str) -> None:
        """Public wrapper: sync working tree to a checkpoint by id."""
        self.sync_working_tree_to_commit(self._resolve(checkpoint_id))

    def sync_working_tree_to_commit(self, commit_id: ObjectID) -> None:
        """Make managed working files EXACTLY match a commit's tree.

        Does not move refs and makes no new commit: deletes managed files
        not present in the target tree, restores modified and deleted ones
        byte-for-byte, prunes directories left empty. Line endings are
        never translated (blob bytes are written verbatim).
        """
        from typing import cast

        from dulwich.objects import Blob as DulwichBlob
        from dulwich.objects import Commit as DulwichCommit
        from dulwich.objects import Tree as DulwichTree

        repo = self.repo
        try:
            commit = cast(DulwichCommit, repo.object_store[commit_id])
            tree = cast(DulwichTree, repo.object_store[commit.tree])
            target_paths: dict[str, ObjectID] = {}
            self._flatten_tree(tree, b"", target_paths)
            root = self._guard.root
            # Delete working FILES not present in target (dirs handled after)
            for p in self._iter_managed_paths():
                rel = p.relative_to(root).as_posix()
                if rel not in target_paths:
                    p.unlink(missing_ok=True)
            # Restore target file contents
            for rel, sha in target_paths.items():
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                blob = cast(DulwichBlob, repo.object_store[sha])
                data = blob.data
                tmp = dest.with_name(dest.name + ".mcp-restore")
                tmp.write_bytes(data)
                os.replace(tmp, dest)
            # Prune empty directories
            for p in sorted(self._iter_dirs(root), key=lambda x: -len(x.parts)):
                try:
                    next(p.iterdir())
                except StopIteration:
                    p.rmdir()
                except OSError:
                    continue
            # Reset index to target so status is immediately consistent.
            from dulwich.index import build_index_from_tree

            build_index_from_tree(
                str(root), repo.index_path(), repo.object_store, tree.id
            )
        except errors.CheckpointNotFoundError:
            raise
        except errors.SafeWorkspaceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise errors.GitError_(f"working-tree sync failed: {exc}") from exc

    def _flatten_tree(
        self, tree: Tree, prefix: bytes, out: dict[str, ObjectID]
    ) -> None:
        from dulwich.objects import Tree as _Tree

        for item in tree.items():
            full = f"{prefix.decode()}/{item.path.decode()}".lstrip("/")
            obj = self.repo.object_store[item.sha]
            if isinstance(obj, _Tree):
                self._flatten_tree(obj, full.encode(), out)
            else:
                out[full] = item.sha

    def _iter_dirs(self, start: Path) -> list[Path]:
        out: list[Path] = []
        stack = [start]
        while stack:
            cur = stack.pop()
            with os.scandir(cur) as it:
                for entry in it:
                    if self._guard.is_internal_or_excluded_dir(entry.name):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                            out.append(Path(entry.path))
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        return out

    def _current_branch_ref(self) -> Ref | None:
        from dulwich.refs import Ref as _Ref

        try:
            sym = self.repo.refs.read_ref(_Ref(b"HEAD"))
            if sym is not None and sym.startswith(b"ref: "):
                return _Ref(sym[5:])
        except Exception:  # noqa: BLE001
            return None
        return None
