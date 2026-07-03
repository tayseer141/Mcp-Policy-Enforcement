from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)

    # Relationship to User
    users = relationship("User", back_populates="role")
    
    # MANY-TO-MANY: Link to Permission through RolePermission
    # This allows the 'role.permissions' access in your engine.py
    permissions = relationship(
        "Permission", 
        secondary="role_permissions", 
        back_populates="roles"
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    # PBKDF2 hash (see app.core.security). Nullable so pre-auth rows can
    # be migrated in place; verify_password fails closed on None.
    password_hash = Column(String, nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"))

    role = relationship("Role", back_populates="users")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)

    # Back reference to roles
    roles = relationship(
        "Role", 
        secondary="role_permissions", 
        back_populates="permissions"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"))
    permission_id = Column(Integer, ForeignKey("permissions.id"))