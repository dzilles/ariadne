import os
import django
import uuid

# Setup django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember, APIToken
from django.contrib.auth.hashers import make_password

def create_setup():
    print("Starting Plane initial setup...")

    # 1. Create main user
    main_user, _ = User.objects.get_or_create(
        email="dzilles@example.com",
        defaults={
            "username": "dzilles",
            "first_name": "Daniel Zilles",
            "password": make_password("password123"),
            "is_active": True,
            "is_staff": True,
            "is_superuser": True
        }
    )

    # 2. Create Workspace
    workspace, _ = Workspace.objects.get_or_create(
        slug="ariadne-workspace",
        defaults={
            "name": "Ariadne Workspace",
            "owner": main_user,
        }
    )

    # Add main user to workspace
    WorkspaceMember.objects.get_or_create(
        workspace=workspace,
        member=main_user,
        defaults={"role": 20} # 20 is usually admin/owner
    )

    # 3. Create Project
    project, _ = Project.objects.get_or_create(
        workspace=workspace,
        identifier="ARI",
        defaults={
            "name": "Ariadne V-Model",
            "description": "Project for Ariadne autonomous agents",
        }
    )

    ProjectMember.objects.get_or_create(
        workspace=workspace,
        project=project,
        member=main_user,
        defaults={"role": 20}
    )

    # 4. Create Agents
    agents = [
        {"name": "Product Owner", "email": "po@ariadne.local"},
        {"name": "Requirements Agent", "email": "req@ariadne.local"},
        {"name": "Architect Agent", "email": "arch@ariadne.local"},
        {"name": "Developer Agent", "email": "dev@ariadne.local"},
        {"name": "Tester Agent", "email": "test@ariadne.local"},
        {"name": "QA Agent", "email": "qa@ariadne.local"},
        {"name": "Orchestrator Agent", "email": "orch@ariadne.local"}
    ]

    print(f"\nWorkspace Slug: {workspace.slug}")
    print(f"Project ID: {project.id}\n")

    for agent_data in agents:
        agent_user, created = User.objects.get_or_create(
            email=agent_data["email"],
            defaults={
                "username": agent_data["name"].lower().replace(" ", "_"),
                "first_name": agent_data["name"],
                "password": make_password("agent_password123"),
                "is_active": True,
                "is_bot": True if hasattr(User, 'is_bot') else False
            }
        )

        WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            member=agent_user,
            defaults={"role": 20}
        )

        ProjectMember.objects.get_or_create(
            workspace=workspace,
            project=project,
            member=agent_user,
            defaults={"role": 20}
        )

        # Generate API Token
        token, t_created = APIToken.objects.get_or_create(
            user=agent_user,
            label="Ariadne Automation",
            defaults={
                "workspace": workspace,
                "token": uuid.uuid4().hex
            }
        )

        print(f"Agent: {agent_data['name']}")
        print(f"  Email: {agent_data['email']}")
        print(f"  API Token: {token.token}\n")

if __name__ == "__main__":
    create_setup()
