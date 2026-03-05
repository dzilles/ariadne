import os
import subprocess
import sys
import shutil
from pathlib import Path

def setup_sandbox():
    """Sets up the Ariadne Docker sandbox environment."""
    print("🚀 Initializing Ariadne Sandbox Environment...")
    
    ariadne_dir = Path(".ariadne")
    sandbox_dir = ariadne_dir / "sandbox"
    workspace_dir = sandbox_dir / "workspace"
    
    # Create directories
    os.makedirs(workspace_dir, exist_ok=True)
    print(f"✅ Created sandbox workspace at {workspace_dir}")
    
    # Seed the workspace with templates if they exist in the main project
    source_templates = Path("docs/templates")
    dest_templates = workspace_dir / "docs" / "templates"
    if source_templates.exists():
        os.makedirs(dest_templates, exist_ok=True)
        # Use shutil.copytree to copy contents, handling if directory already exists
        for item in os.listdir(source_templates):
            s = source_templates / item
            d = dest_templates / item
            if s.is_file():
                shutil.copy2(s, d)
        print("✅ Copied project templates into sandbox.")

    # Create Dockerfile
    dockerfile_content = """FROM python:3.12-slim

RUN apt-get update && apt-get install -y \\
    git \\
    curl \\
    wget \\
    build-essential \\
    nodejs \\
    npm \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Keep the container running
CMD ["tail", "-f", "/dev/null"]
"""
    
    with open(sandbox_dir / "Dockerfile", "w") as f:
        f.write(dockerfile_content)
    
    # Create docker-compose.yml
    docker_compose_content = """version: '3.8'

services:
  ariadne-sandbox:
    build: .
    container_name: ariadne-sandbox
    volumes:
      - ./workspace:/workspace
    network_mode: bridge
"""
    
    with open(sandbox_dir / "docker-compose.yml", "w") as f:
        f.write(docker_compose_content)
        
    print("✅ Created Dockerfile and docker-compose.yml")
    
    # Run docker-compose
    print("⏳ Building and starting the sandbox container (this may take a minute)...")
    
    try:
        # Prefer 'docker compose' (V2), fallback to 'docker-compose' (V1)
        try:
            subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
            cmd = ["docker", "compose", "up", "-d", "--build"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            cmd = ["docker-compose", "up", "-d", "--build"]
            
        subprocess.run(cmd, cwd=str(sandbox_dir), check=True)
        print("🎉 Sandbox container started!")
        
        # Initialize git inside the container
        print("🔧 Initializing Git repository in sandbox...")
        init_cmds = [
            "git config --global --add safe.directory /workspace",
            "git config --global user.email 'ariadne@ai.com'",
            "git config --global user.name 'Ariadne AI'",
            "git init",
            "git add docs/templates" if source_templates.exists() else "echo 'No templates to add'",
            "git commit -m 'Initial commit with templates' || echo 'Nothing to commit'"
        ]
        
        # Combine commands into one shell execution
        full_cmd = " && ".join(init_cmds)
        subprocess.run(["docker", "exec", "ariadne-sandbox", "bash", "-c", full_cmd], check=True)
        
        print("🎉 Sandbox environment is up and fully seeded!")
        print("You can interact with it via tools or manually using: docker exec -it ariadne-sandbox bash")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start or configure docker container: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Error: Docker or Docker Compose is not installed or not in PATH.", file=sys.stderr)
        sys.exit(1)
