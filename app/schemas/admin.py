"""
Pydantic models for the admin JSON API.

These define the public contract of every endpoint under
/api/v1/admin/*. The HTML admin pages, automated tests, and any
future external admin tool all speak JSON to these endpoints.

Error envelope
--------------
On failure, endpoints raise HTTPException with a structured detail
of the form:
    {"code": "user_exists", "message": "A user with that username already exists."}

The `code` is stable and machine-friendly (used by the existing
template notice system); the `message` is human-friendly and the
default rendering when no localised text is available.
"""

from typing import Optional

from pydantic import BaseModel, Field


# =====================================================================
# Public resource representations
# =====================================================================

class UserPublic(BaseModel):
    """A user record as exposed by the admin API."""

    username: str
    role: Optional[str] = Field(
        default=None,
        description="Name of the assigned role, or None if the user has no role.",
    )


class RolePublic(BaseModel):
    """A role with its permission set and currently assigned users."""

    name: str
    permissions: list[str] = Field(
        default_factory=list,
        description="Names of permissions attached to this role.",
    )
    users: list[str] = Field(
        default_factory=list,
        description="Usernames currently assigned to this role.",
    )
    is_system: bool = Field(
        default=False,
        description="True for the built-in admin role; system roles cannot be deleted.",
    )


class PermissionPublic(BaseModel):
    """A permission, including provenance and usage."""

    name: str
    is_tool_backed: bool = Field(
        ...,
        description=(
            "True if this permission name matches a registered @mcp.tool(). "
            "Tool-backed permissions are auto-recreated on next server boot if deleted."
        ),
    )
    used_in_roles: list[str] = Field(
        default_factory=list,
        description="Names of roles that currently include this permission.",
    )


# =====================================================================
# Request bodies
# =====================================================================

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1)
    role_name: str = Field(..., min_length=1)


class AssignRoleRequest(BaseModel):
    role_name: str = Field(..., min_length=1)


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=1)


class AddPermissionRequest(BaseModel):
    permission_name: str = Field(..., min_length=1)


# =====================================================================
# Generic action response
# =====================================================================

class ActionResponse(BaseModel):
    """
    Standard success envelope for write actions that don't return a
    full resource (e.g. role assignment, permission attach/detach).
    """

    success: bool = True
    code: str = Field(
        ...,
        description="Stable machine-friendly outcome code (e.g. 'user_created').",
    )
    message: str = Field(
        ...,
        description="Human-friendly description of what happened.",
    )