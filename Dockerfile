FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Update package lists and install necessary dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common curl pkg-config libcairo2-dev libportaudio2 \
    libgirepository1.0-dev gobject-introspection gir1.2-girepository-2.0 \
    gir1.2-gtk-3.0 build-essential libffi-dev libssl-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev wget llvm libncurses5-dev \
    libncursesw5-dev xz-utils tk-dev liblzma-dev python3-openssl python3-gi \
    python3-gi-cairo liblo-dev libportmidi-dev libsndfile1-dev portaudio19-dev \
    libasound2-dev libjack-jackd2-dev ca-certificates alsa-utils pulseaudio-utils \
    git jq ripgrep less nano make \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

    
# Install Astral's `uv` standalone installer (no Python required). We move the
# installed binary into /usr/local/bin so it's on PATH for subsequent RUN steps.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && if [ -f /root/.local/bin/uv ]; then mv /root/.local/bin/uv /usr/local/bin/uv; fi \
    && if [ -f /usr/bin/uv ]; then mv /usr/bin/uv /usr/local/bin/uv; fi \
    && uv --version

# Create base app directory and use uv to install Python and create a venv.
RUN mkdir -p /base_app

WORKDIR /base_app

# Install Python 3.12 into a shared, world-readable location (not under /root)
# so the non-root user can use it, then create a venv in /opt/venv.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.12 && uv venv /opt/venv --python 3.12

# Add venv to PATH (this makes it the default python/pip globally in the container)
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/venv/"

# Copy requirements and use uv's pip interface to install dependencies into the venv
COPY requirements.txt /base_app/requirements.txt
# Install Python packages into the uv-created venv using uv's pip wrapper.
# This keeps the command simple (like `pip install -r requirements.txt`) but
# ensures uv's environment is used.
RUN uv pip install -r /base_app/requirements.txt

# Outils d'analyse audio hors-ligne (scripts/analyze_loops.py,
# remove_silence.py, cut_loop.py) :beat tracking librosa, scipy, soundfile.
# Copie séparée pour que la couche reste en cache tant que ce fichier ne
# change pas.
COPY requirements-analysis.txt /base_app/requirements-analysis.txt
RUN uv pip install -r /base_app/requirements-analysis.txt


# --- Non-root user -----------------------------------------------------------
# Create a dedicated user aligned with the host user (uid 1000 by default) so
# that files written into the bind-mounted data volume keep the host owner.
# The user is added to the `audio` (gid 29) and `video` (gid 44) groups so it
# can access /dev/snd when the device is shared with the container.
# The ubuntu:24.04 base image already ships a user `ubuntu` with UID 1000.
# We rename it to `mkr` (keeping UID 1000 so files written into the bind-mounted
# data volume stay owned by the host user) and add it to the audio/video groups
# so it can access /dev/snd when the device is shared with the container.
RUN groupadd -g 29 audio 2>/dev/null || true \
    && groupadd -g 44 video 2>/dev/null || true \
    && usermod -l mkr -d /home/mkr -m ubuntu \
    && usermod -aG audio,video mkr

# Copy application code and scripts
COPY app /base_app/app
COPY scripts /base_app/scripts
COPY triggers.example.json /base_app/triggers.example.json

# Set working directory
WORKDIR /base_app/app

# Data folders + app + venv + uv python owned by the non-root user (GID 1000 is already correct)
RUN mkdir -p /monkey-resonance/records /monkey-resonance/saved_effects /monkey-resonance/saved_midi_maps \
    && chown -R mkr /monkey-resonance /base_app /opt/venv /opt/uv-python

# Drop privileges
USER mkr

# Expose port 80
EXPOSE 8005

# Default command: run the app interactively
# (no ENTRYPOINT, so `docker compose run mkr python ...` / `ruff ...` work directly)
CMD ["python", "-i", "main.py"]