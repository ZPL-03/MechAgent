"""Studio API 密钥认证、角色和项目访问控制。"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


class AuthenticationError(ValueError):
    """请求没有有效凭据。"""


class AuthorizationError(PermissionError):
    """主体没有执行所需操作的角色或项目权限。"""


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]
    project_ids: frozenset[str]
    organization: str = "local"

    def can(self, action: str, project_id: str, organization: str | None = None) -> bool:
        if organization is not None and self.organization not in {"*", organization}:
            return False
        if "admin" in self.roles:
            return True
        if project_id not in self.project_ids:
            return False
        role_actions = {
            "viewer": {"read", "inspect"},
            "runner": {"read", "inspect", "submit", "cancel", "retry"},
        }
        return any(action in role_actions.get(role, set()) for role in self.roles)


class ApiKeyAuthenticator:
    """用预存 SHA-256 摘要验证 Bearer API key。"""

    def __init__(
        self,
        key_digest: str,
        principals: tuple[tuple[str, Principal], ...] = (),
    ) -> None:
        normalized = key_digest.strip().lower()
        if normalized and (
            len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized)
        ):
            raise ValueError("auth_api_key_sha256 必须是 64 位小写 SHA-256。")
        self.key_digest = normalized
        self.principals = tuple(principals)

    def authenticate(self, token: str | None, principal: Principal | None = None) -> Principal:
        if token is None:
            raise AuthenticationError("需要有效的 Bearer API key。")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for configured_digest, configured_principal in self.principals:
            if hmac.compare_digest(digest, configured_digest):
                return configured_principal
        if (
            self.key_digest
            and principal is not None
            and hmac.compare_digest(digest, self.key_digest)
        ):
            return principal
        raise AuthenticationError("API key 无效。")


def ensure_authorized(
    principal: Principal, action: str, project_id: str, organization: str | None = None
) -> None:
    if not principal.can(action, project_id, organization):
        raise AuthorizationError("主体没有该项目的操作权限。")


def normalize_identity_fields(
    *,
    subject: str,
    organization: str,
    roles: list[str] | tuple[str, ...],
    projects: list[str] | tuple[str, ...],
) -> tuple[str, str, frozenset[str], frozenset[str]]:
    """Normalize the persisted identity fields and reject ambiguous scopes."""

    normalized_subject = subject.strip()
    normalized_organization = organization.strip()
    normalized_roles = frozenset(item.strip().lower() for item in roles if item.strip())
    normalized_projects = frozenset(item.strip() for item in projects if item.strip())
    if not normalized_subject or len(normalized_subject) > 128:
        raise ValueError("主体标识必须为 1 到 128 个字符。")
    if not normalized_organization or len(normalized_organization) > 128:
        raise ValueError("组织标识必须为 1 到 128 个字符。")
    if not normalized_roles or not normalized_roles.issubset({"admin", "runner", "viewer"}):
        raise ValueError("roles 只能包含 admin、runner 或 viewer。")
    if normalized_organization == "*" and "admin" not in normalized_roles:
        raise ValueError("只有 admin 主体可以使用跨组织范围。")
    if not normalized_projects or any(len(item) > 128 for item in normalized_projects):
        raise ValueError("projects 必须包含长度不超过 128 的非空项目标识。")
    return normalized_subject, normalized_organization, normalized_roles, normalized_projects
