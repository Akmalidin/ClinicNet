from rest_framework import serializers

from .models import Permission, Role, User, UserRole


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "phone", "job_title", "is_active")
        read_only_fields = ("id",)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("id", "code", "category", "description")


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_codes = serializers.SlugRelatedField(
        source="permissions",
        slug_field="code",
        queryset=Permission.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = Role
        fields = ("id", "name", "codename", "description", "is_system", "permissions", "permission_codes")


class UserRoleSerializer(serializers.ModelSerializer):
    user_display = serializers.CharField(source="user.__str__", read_only=True)
    role_display = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = UserRole
        fields = (
            "id",
            "user",
            "user_display",
            "role",
            "role_display",
            "branch_scope",
            "branches",
            "is_active",
            "granted_by",
            "granted_at",
        )
        read_only_fields = ("id", "granted_by", "granted_at")

    def validate(self, attrs):
        branch_scope = attrs.get("branch_scope", getattr(self.instance, "branch_scope", None))
        branches = attrs.get("branches", None)
        if branch_scope == "specific_branches" and self.instance is None and not branches:
            raise serializers.ValidationError(
                {"branches": "Укажите филиалы для branch_scope=specific_branches."}
            )
        return attrs
