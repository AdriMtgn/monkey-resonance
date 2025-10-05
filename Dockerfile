FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Update package lists and install necessary dependencies
RUN apt update && apt install -y \
    software-properties-common \
    curl \
    pkg-config \
    libcairo2-dev \
    libportaudio2 \
    libgirepository1.0-dev \
    gobject-introspection \
    gir1.2-girepository-2.0 \
    gir1.2-gtk-3.0 \
    build-essential \
    libffi-dev \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    wget \
    llvm \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    liblzma-dev \
    python3-openssl \
    python3-gi \
    python3-gi-cairo \    
    && rm -rf /var/lib/apt/lists/*

# Install Python build dependencies and audio libs (kept from earlier list)
RUN apt update && apt install -y \
    liblo-dev \
    libportmidi-dev \
    libsndfile1-dev \
    portaudio19-dev \
    libasound2-dev \
    libjack-jackd2-dev \
    ca-certificates \
    alsa-utils \
    pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Astral's `uv` standalone installer (no Python required). We move the
# installed binary into /usr/local/bin so it's on PATH for subsequent RUN steps.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && if [ -f /root/.local/bin/uv ]; then mv /root/.local/bin/uv /usr/local/bin/uv; fi \
    && if [ -f /usr/bin/uv ]; then mv /usr/bin/uv /usr/local/bin/uv; fi \
    && uv --version

# Create base app directory and use uv to install Python and create a venv.
WORKDIR /base_app
RUN mkdir -p /base_app

# Install Python 3.12 via uv and create a project venv (.venv)
RUN uv python install 3.12 && uv venv --python 3.12

# Ensure the project's venv is on PATH
ENV PATH="/base_app/.venv/bin:$PATH"

# Copy requirements and use uv's pip interface to install dependencies into the venv
COPY requirements.txt /base_app/requirements.txt
# Install Python packages into the uv-created venv using uv's pip wrapper.
# This keeps the command simple (like `pip install -r requirements.txt`) but
# ensures uv's environment is used.
RUN uv pip install -r /base_app/requirements.txt


# Copy application code
COPY app /base_app/app

# Set working directory
WORKDIR /base_app/app

RUN mkdir /monkey-resonance

# Expose port 80
EXPOSE 80

# Default command: run the app interactively
ENTRYPOINT [ "python" ]

CMD ["-i","main.py"]