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
    docker_compose_content = f"""version: '3.8'

services:
  ariadne-sandbox:
    build: .
    container_name: ariadne-sandbox
    user: "${{UID:-1000}}:${{GID:-1000}}"
    environment:
      - HOME=/workspace
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
        env = os.environ.copy()
        if hasattr(os, 'getuid'):
            env['UID'] = str(os.getuid())
            env['GID'] = str(os.getgid())

        # Prefer 'docker compose' (V2), fallback to 'docker-compose' (V1)
        try:
            subprocess.run(["docker", "compose", "version"], check=True, capture_output=True, env=env)
            cmd = ["docker", "compose", "up", "-d", "--build"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            cmd = ["docker-compose", "up", "-d", "--build"]
            
        subprocess.run(cmd, cwd=str(sandbox_dir), check=True, env=env)
        print("🎉 Sandbox container started!")
        
        # Initialize git on the host so permissions remain correct for the user
        print("🔧 Initializing Git repository in sandbox...")
        subprocess.run(["git", "init"], cwd=str(workspace_dir), check=True)
        subprocess.run(["git", "config", "user.email", "ariadne@ai.com"], cwd=str(workspace_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Ariadne AI"], cwd=str(workspace_dir), check=True)
        
        if source_templates.exists():
            subprocess.run(["git", "add", "docs/templates"], cwd=str(workspace_dir), check=True)
            
        subprocess.run(["git", "commit", "-m", "Initial commit with templates", "--allow-empty"], cwd=str(workspace_dir), check=True)
        
        # Mark directory as safe inside the container
        subprocess.run(["docker", "exec", "ariadne-sandbox", "git", "config", "--global", "--add", "safe.directory", "/workspace"], check=True)
        
        print("🎉 Sandbox environment is up and fully seeded!")
        print("You can interact with it via tools or manually using: docker exec -it ariadne-sandbox bash")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start or configure docker container: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Error: Docker or Docker Compose is not installed or not in PATH.", file=sys.stderr)
        sys.exit(1)
