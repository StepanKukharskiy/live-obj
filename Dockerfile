FROM node:20-slim
# Install Python 3.11 and X11/graphics libraries for OCP
RUN apt-get update \
 && apt-get install -y python3.11 python3-pip libgl1 libxrender1 libxext6 \
 && rm -rf /var/lib/apt/lists/*
# Install optional CAD kernel dependencies used by live_obj_executor_v02.py
RUN python3.11 -m pip install --no-cache-dir --break-system-packages cadquery trimesh shapely manifold3d
WORKDIR /app
# Copy package files
COPY package*.json ./
# Install dependencies and prepare
RUN npm ci
RUN npm run prepare
# Copy application code
COPY . .
# Build the application
RUN npm run build
# Set the start command
CMD ["node", "build/index.js"]
