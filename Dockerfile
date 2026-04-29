FROM node:18-slim

# Install Python 3.11
RUN apt-get update \
    && apt-get install -y python3.11 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install Node dependencies
RUN npm install

# Copy application code
COPY . .

# Build (if needed)
RUN npm run build || true

# Set the start command
CMD ["node", "build/index.js"]
