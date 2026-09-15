FROM python:3.13-slim-bookworm

# 1. Install prerequisites (curl, ca-certificates, and git are required for Claude Code)
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Add an explicit non-root system user & group
RUN groupadd -g 1001 user && \
    useradd -u 1001 -g user -m -s /bin/bash user

# Install libraries system wide
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Add ~/.local/bin and npm global bin to PATH
ENV HOME=/home/user
ENV PATH="$HOME/.local/bin:${PATH}"

# Install claude as the target user so files land in /home/user/.claude
RUN su - user -c "curl -fsSL https://claude.ai/install.sh | bash"

# Install Node.js (LTS) via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install IBM Bob so files land in /home/user/.bob
RUN curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash

# Workaround to avoid installing massive NVIDIA Cuda libraries with txtai and pytorch
RUN pip install --no-cache-dir txtai --extra-index-url https://download.pytorch.org/whl/cpu torch

# Copy the project root directory
COPY . /mellea-skills-compiler

# Copy claude commands, data and schemas directories (owned by user, not root)
RUN cp -r /mellea-skills-compiler/.claude/. $HOME/.claude/ && \
    chown -R user:user $HOME/.claude/

# Copy Bob skills, data and schemas directories (owned by user, not root)
RUN cp -r /mellea-skills-compiler/.bob/. $HOME/.bob/ && \
    chown -R user:user $HOME/.bob/

# Replace ".claude/" with the real home path in all claude commands
RUN find $HOME/.claude/commands -type f -name "*.md" | while read f; do \
        sed -i "s|\.claude/|${HOME}/.claude/|g" "$f"; \
    done

# Replace ".bob/" with the real home path in all bob skills
RUN find $HOME/.bob/skills -type f -name "*.md" | while read f; do \
        sed -i "s|\.bob/|${HOME}/.bob/|g" "$f"; \
    done

# Install the mellea-skills-compiler package system-wide
RUN pip install --no-cache-dir /mellea-skills-compiler

# Set Compatibility YAML path for Mellea 0.7
ENV MELLEA_SKILLS_COMPILER_COMPATIBILITY_YAML=/home/user/.claude/data/compatibility.yaml

# Copy welcome script and make it executable
RUN cp /mellea-skills-compiler/welcome.sh /usr/local/bin/welcome.sh && \
    chmod +x /usr/local/bin/welcome.sh

# Show welcome message and clear screen on interactive shell start
RUN echo 'source /usr/local/bin/welcome.sh' >> /home/user/.bashrc

# Remove code directory and all of its content in order to maintain a
# single source of truth: $HOME/.claude and $HOME/.bob
RUN rm -rf /mellea-skills-compiler

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Restore the sentinel UID expected by image scanners.
USER 1001

CMD ["/bin/bash"]
