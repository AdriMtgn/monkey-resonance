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
    pipewire-alsa \
    pipewire-pulse \
    pipewire-jack \
    && rm -rf /var/lib/apt/lists/*

# Add deadsnakes PPA
RUN add-apt-repository ppa:deadsnakes/ppa

# Update package lists again and install Python 3.12 and other dependencies
RUN apt update && apt install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    pipewire \
    pipewire-audio-client-libraries \
    libspa-0.2-bluetooth \
    libspa-0.2-jack \
    wireplumber \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as the default python version
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Create and activate a virtual environment
RUN python3.12 -m venv /base_app/venv
ENV PATH="/base_app/venv/bin:$PATH"

# Install dependencies within the virtual environment
COPY requirements.txt /base_app/requirements.txt
RUN pip install -r /base_app/requirements.txt

# Copy application code
COPY app /base_app/app

# Set working directory
WORKDIR /app

# Expose port 80
EXPOSE 80

# Start the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]